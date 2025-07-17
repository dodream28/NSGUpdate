import pyodbc

class DBLogger:
    def __init__(self, conn_str):
        self.conn = pyodbc.connect(conn_str)
        self.cursor = self.conn.cursor()

    def log(self,
            resource_group: str,
            nsg_name: str,
            rule_name: str,
            action_type: str,
            register_date=None,
            expiry_date=None,
            ID=None,
            detail_text=None):
        sql = """
        INSERT INTO NSGChangeLog
            (Timestamp, ResourceGroup, NSGName, RuleName, ActionType,
             RegisterDate, ExpiryDate, ID, DetailText)
        VALUES
            (GETDATE(), ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.cursor.execute(sql,
            resource_group,
            nsg_name,
            rule_name,
            action_type,
            register_date,
            expiry_date,
            ID,
            detail_text
        )
        self.conn.commit()