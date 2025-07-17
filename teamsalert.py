import requests, json

class TeamsAlert:
    def __init__(self, webhook_url, check_type):
        self.webhook_url = webhook_url
        self.check_type = check_type

    def send(self, message, facts_extra=None):
        facts = [
            {'name': 'CheckType', 'value': self.check_type},
            {'name': 'Message', 'value': message}
        ]
        if facts_extra:
            facts.extend(facts_extra)

        body = {
            '@type': 'MessageCard',
            '@context': 'http://schema.org/extensions',
            'themeColor': '0076D7',
            'summary': 'NSG 검사 결과 알림',
            'sections': [{
                'activityTitle': 'NSG 검사 결과',
                'wrap': True,
                'markdown': True,
                'facts': facts,
                'activitySubtitle': 'NSG 모니터링 자동화',
            }]
        }
        headers = {'Content-Type': 'application/json'}
        resp = requests.post(self.webhook_url, headers=headers, data=json.dumps(body))
        resp.raise_for_status()
        return resp
