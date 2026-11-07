
import os
import pymysql
from dotenv import load_dotenv

load_dotenv()

try:
    connection = pymysql.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "8801")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )

    with connection.cursor() as cursor:
        cursor.execute("SELECT DATABASE()")
        result = cursor.fetchone()

        print("MySQL Connected Successfully!")
        print("Database:", result[0])

    connection.close()

except Exception as e:
    print("MySQL Connection Failed:", e)
