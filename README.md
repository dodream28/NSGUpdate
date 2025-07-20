# NSG 업데이트 자동화 README
---
## 📖 사용자 가이드

**1. 추가할 Rule 작성**
    Update.xlsx 파일의 각 행에 다음 항목을 입력하세요.

- 실사용자, 출발IP, 도착IP, 서비스포트, 사용목적, 프로토콜, 만료일, ID

**2. 엑셀 파일 리포지토리 반영**
- 기존 Update.xlsx 파일은 삭제한 뒤 새 파일을 동일 경로에 업로드합니다.

**3. 파이프라인 실행**
- Azure DevOps → Pipelines → NSG_업데이트 선택
- Run pipeline 클릭
- AssignedTo(작업자) 파라미터에서 담당자를 선택

**4. 자동화 진행 확인**
파이프라인 로그가 정상 완료되면,
- Teams 채널에서 생성·에러 알림을 확인
- SQL DB (NSGChangeLog 테이블) 에 기록된 로그를 조회

**5. 에러 처리**
- 에러 발생 시, NSGChangeLog 테이블의 ActionType = ERROR 레코드를 확인하여 원인 파악

**6. Change Request 연계**
- 룰 생성 후 Logic App을 통해 자동 생성된 Change Request(Task)에 Parent 링크를 등록하여 추적 체계를 완성

---

## 💻 코드 및 기능 설명

| 파일명                  | 역할 및 설명                                                                      |
| -------------------- | ---------------------------------------------------------------------------- |
| **dblogger.py**      | 작업 결과를 SQL Server **NSPChangeLog** 테이블에 저장하는 모듈<br>- `log()` 메서드로 각 필드 분리 삽입 |
| **teamsalert.py**    | 생성·에러 결과를 Microsoft Teams 웹훅 채널로 알림 발송                                       |


**NSGautoupdate.py** 

**1.** NSG_Info.xlsx (DestinationIP → NSG/Subscription/ServiceCode 매핑)
**2.** Update_SECC.xlsx (신규 룰 정의)
**3.** Azure SDK 호출을 통해 NSG 보안 규칙 생성
**4.** DB 로깅 & Teams 알림 & Logic App 호출 |
| NSG_Info.xlsx | DestinationIP별로
- Subscription ID
- ResourceGroup (ID 경로 중 5번째)
- NSGName
- ServiceCode |
| Update_SECC.xlsx | 추가·생성할 NSG 보안 규칙을 상세히 기입
(출발IP, 도착IP, 포트, 프로토콜, 만료일, ID, 사용목적 등) |

---

## 🔍 확인 가능한 정보

**파이프라인 로그**
- 스크립트 실행 단계별 출력 메시지
- 실패한 룰에 대한 예외 메시지

**Teams 알림**
- 생성 성공/실패 요약
- 개별 룰별 우선순위 및 에러 상세

**DB 테이블 (NSGChangeLog)**
| 필드            | 설명                               |
| ------------- | -------------------------------- |
| Timestamp     | 작업 수행 시각 (DB 서버 시간, `GETDATE()`) |
| ResourceGroup | 룰이 등록된 리소스 그룹                    |
| NSGName       | 네트워크 보안 그룹 이름                    |
| RuleName      | 생성된 보안 규칙 이름                     |
| ActionType    | `CREATE` / `ERROR`               |
| RegisterDate  | 규칙에 기입된 등록일                      |
| ExpiryDate    | 규칙에 기입된 만료일                      |
| ID            | SR 번호 또는 식별자                     |
| DetailText    | 사용 목적 등 설명 텍스트                   |
