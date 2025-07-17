import pandas as pd
from teamsalert import TeamsAlert
from dblogger import DBLogger
from datetime import datetime
from azure.identity import ClientSecretCredential
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.network.models import SecurityRule
import re
import os
import requests


DB_CONN = os.getenv('DB_CONN')
TEAMS_WEBHOOK = os.getenv('TEAMS_WEBHOOK')
LOGICAPP_URL = os.getenv('LOGICAPP_URL')
assigned_To = os.getenv('Assigned_To')

# ========== 인증 (Service Principal 기반) ==========
def get_credential():
    return ClientSecretCredential(
        tenant_id=os.getenv('AZ_TENANT_ID'),
        client_id=os.getenv('AZ_CLIENT_ID'),
        client_secret=os.getenv('AZ_CLIENT_SECRET')
    )

# —— 엑셀 로드 & 컬럼 정리 ——
def load_excels(update_path, guide_path):
    upd   = pd.read_excel(update_path)
    guide = pd.read_excel(guide_path)

    # 공백·줄바꿈 제거
    upd.columns   = upd.columns.str.strip().str.replace('\n','', regex=True)
    guide.columns = guide.columns.str.strip().str.replace('\n','', regex=True)

    # 필수 컬럼 변환
    upd['만료일']    = pd.to_datetime(upd['만료일'])
    upd['등록일']    = pd.Timestamp.today().normalize()
    upd['출발IP']    = upd['출발IP'].astype(str).str.strip().str.replace('\n','', regex=True)
    upd['도착IP']   = upd['도착IP'].astype(str).str.strip().str.replace('\n','', regex=True)
    upd['서비스포트'] = upd['서비스포트'].astype(str).str.strip()
    upd['프로토콜']  = upd['프로토콜'].str.upper()

    return upd, guide

# —— Description 빌드 ——
def build_description(defn):
    return (
        f"등록일: {defn['RegisterDate']:%Y-%m-%d} / "
        f"만료일: {defn['ExpiryDate']:%Y-%m-%d} / "
        f"ID: {defn['ID']} / "
        f"{defn['DescriptionNote']}"
    )

# —— 룰 네이밍 ——
def generate_unique_rule_name(client, rg, nsg_name, service_code, port_csv):
    # 공백 제거, 쉼표→점 변환
    port_for_name = port_csv.replace(' ', '').replace(',', '.')
    base = f"allow-FromUser1-To{service_code}-{port_for_name}"
    existing = [r.name for r in client.network_security_groups.get(rg, nsg_name).security_rules]
    if base not in existing:
        return base
    idx = 2
    while True:
        cand = f"allow-FromUser{idx}-To{service_code}-{port_for_name}"
        if cand not in existing:
            return cand
        idx += 1

# —— 시작 우선순위 & 사용 집합 ——
def get_start_priority_and_set(client, rg, nsg_name):
    rules = client.network_security_groups.get(rg, nsg_name).security_rules
    used = set(r.priority for r in rules if r.priority is not None)
    max_prio = max(used) if used else 4096
    return max_prio - 1, used

# —— 가이드 시트 조회 ——
def find_nsg_info(dest_ip, guide_df):
    row = guide_df[guide_df['DestinationIP'] == dest_ip]
    if row.empty:
        return None
    r = row.iloc[0]
    return {
        'SubscriptionId': r['SubscriptionID'],
        'ResourceGroup' : r['ID'].split('/')[4],
        'NSGName'       : r['NSGName'],
        'ServiceCode'   : r['ServiceCode']
    }

# —— 신규 생성 정의만 모으기 ——
def classify_creates(upd_df):
    df = upd_df.copy()
    df.columns = df.columns.str.strip().str.replace('\n','', regex=True)
    groups = df.groupby(['도착IP','서비스포트','프로토콜'])
    defs = []
    for (dest, ports, proto), grp in groups:
        defs.append({
            'DestinationIP': dest,
            'PortCSV'      : str(ports),
            'Ports'        : [p.strip() for p in str(ports).split(',')],
            'Protocol'     : proto,
            'SourceIPs'    : grp['출발IP'].tolist(),
            'RegisterDate' : grp['등록일'].iloc[0],
            'ExpiryDate'   : grp['만료일'].iloc[0],
            'ID'           : grp['ID'].iloc[0],
            'DescriptionNote': grp['사용목적'].iloc[0]
        })
    return defs

# —— 룰 생성 및 로깅 ——
def register_rule(client, rg, nsg_name, defn, priority, db_logger, teams):
    rule_name = generate_unique_rule_name(
        client, rg, nsg_name, defn['ServiceCode'], defn['PortCSV']
    )
    sec_rule = SecurityRule(
        name=rule_name,
        protocol=defn['Protocol'],
        source_address_prefixes=defn['SourceIPs'],
        source_port_range='*',
        destination_address_prefix=defn['DestinationIP'],
        destination_port_ranges=defn['Ports'],
        access='Allow',
        direction='Inbound',
        priority=priority,
        description=build_description(defn)
    )
    client.security_rules.begin_create_or_update(rg, nsg_name, rule_name, sec_rule).result()
    

    # DB 기록 (필드 분할)
    db_logger.log(
        resource_group=rg,
        nsg_name=nsg_name,
        rule_name=rule_name,
        action_type='CREATE',
        register_date=defn['RegisterDate'].date(),
        expiry_date=defn['ExpiryDate'].date(),
        ID=defn['ID'],
        detail_text=defn['DescriptionNote']
    )


    # Teams 알림
    teams.send(f"➕ 생성: {rule_name} (Priority={priority}) (SrcIP={defn['SourceIPs']}) (DstIP={defn['DestinationIP']})", [])

    # LogicApp SR 생성

    # 2) 페이로드에 추가
    payload = {
        "Assigned_To":   assigned_To,
        "ruleName":      rule_name,
        "resourceGroup": rg,
        "nsgName":       nsg_name,
        "priority":      priority,
        "destinationIP": defn['DestinationIP'],
        "sourceIPs":     defn['SourceIPs'],
        "serviceCode":   defn['ServiceCode'],
        "registerDate":  defn['RegisterDate'].strftime('%Y-%m-%d'),
        "expiryDate":    defn['ExpiryDate'].strftime('%Y-%m-%d'),
        "ID":            defn['ID'],
        "description":   defn['DescriptionNote']
    }

    try:
        requests.post(LOGICAPP_URL, json=payload, timeout=10)
    except Exception as ex:
        db_logger.log(
            resource_group=rg,
            nsg_name=nsg_name,
            rule_name=rule_name,
            action_type='ERROR',
            register_date=None,
            expiry_date=None,
            ID=defn['ID'],
            detail_text=f"LogicApp POST failed: {ex}"
        )



    return rule_name, priority

# —— 메인 흐름 ——
def main(update_path, guide_path):
    upd_df, guide_df = load_excels(update_path, guide_path)
    creates = classify_creates(upd_df)
    cred     = get_credential()
    db_logger = DBLogger(DB_CONN)
    teams     = TeamsAlert(webhook_url=TEAMS_WEBHOOK, check_type='NSG Update')

    created = []
    warnings = []

    # NSG별로 묶기
    nsg_map = {}
    for d in creates:
        info = find_nsg_info(d['DestinationIP'], guide_df)
        if not info:
            warnings.append(d['DestinationIP'])
            continue
        d.update(info)
        key = (info['SubscriptionId'], info['ResourceGroup'], info['NSGName'], info['ServiceCode'])
        nsg_map.setdefault(key, []).append(d)

    # NSG별 처리
    for (sub_id, rg, nsg, svc), defs in nsg_map.items():
        client = NetworkManagementClient(cred, sub_id)
        next_prio, used_priorities = get_start_priority_and_set(client, rg, nsg)

        for defn in defs:
            # 충돌 없는 우선순위 찾기
            while next_prio in used_priorities:
                next_prio -= 1
            priority = next_prio
            used_priorities.add(priority)
            next_prio -= 1

            try:
                name, prio = register_rule(client, rg, nsg, defn, priority, db_logger, teams)
                created.append((name, prio))
            except Exception as e:
                err_detail = f"Failed to create rule for {defn['DestinationIP']} ports={defn['PortCSV']}: {e}"
                
                # 에러 로그 저장
                db_logger.log(
                    resource_group=rg,
                    nsg_name=nsg,
                    rule_name=defn['ID'],
                    action_type='ERROR',
                    register_date=None,
                    expiry_date=None,
                    ID=defn['ID'],
                    detail_text=err_detail
                )
                teams.send(f"❌ 생성 실패: {defn['DestinationIP']} ports={defn['PortCSV']} Err_detail={e}", [])

    # 최종 요약
    total_created = len(created)
    total_warns   = len(warnings)
    sample_facts  = [{'name': n, 'value': str(p)} for n, p in created]
    summary = f"✅ 생성 완료: {total_created}개"
    teams.send(summary, facts_extra=sample_facts)

    # 가이드 누락 요약 알림
    if warnings:
        warn_summary = f"⚠️ 가이드 누락: {len(warnings)}개 IP"
        warn_facts   = [{'name': ip, 'value': ''} for ip in warnings]
        teams.send(warn_summary, facts_extra=warn_facts)

if __name__ == '__main__':
    main('update_SECC.xlsx', 'NSG_Info.xlsx')