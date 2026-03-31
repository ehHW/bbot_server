import pymysql
pymysql.install_as_MySQLdb()

from bbot_server.celery import app as celery_app

__all__ = ("celery_app",)