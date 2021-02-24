import os

import peewee as pw
import datetime


db = pw.SqliteDatabase(None)


class BaseModel(pw.Model):
    class Meta:
        database = db


class MWText(BaseModel):
    mediawiki_link = pw.CharField(primary_key=True)
    url = pw.CharField(unique=True)
    rev_id = pw.IntegerField()
    text = pw.CharField()
    html = pw.CharField()
    title = pw.CharField()
    file_safe_url = pw.CharField()
    scraped_at = pw.DateTimeField(default=datetime.datetime.now)
    created_at = pw.DateTimeField(default=datetime.datetime.now)
    modified_at = pw.DateTimeField(default=datetime.datetime.now)
    sqlite_created_at = pw.DateTimeField(default=datetime.datetime.now)


def add_text(
    mediawiki_link, url, rev_id, text, html, title, file_safe_url, created_at, modified_at
):
    return MWText.create(
        mediawiki_link=mediawiki_link,
        url=url,
        rev_id=rev_id,
        text=text,
        html=html,
        title=title,
        file_safe_url=file_safe_url,
        created_at=created_at,
        modified_at=modified_at
    )


def mwtext_exists(mediawiki_link):
    return MWText.select().where(MWText.mediawiki_link == mediawiki_link).count() > 0


def get_mwtext(mediawiki_link):
    return MWText.get(MWText.mediawiki_link == mediawiki_link)


def mwtext_exists_by_url(url):
    return MWText.select().where(MWText.url == url).count() > 0


def mwtext_count():
    return MWText.select().count()


def get_mwtext_by_url(url):
    return MWText.get(MWText.url == url)


def get_last_modified():
    return MWText.select().order_by(MWText.sqlite_created_at.desc()).get()


def db_path(output_dir):
    return output_dir + os.sep + "scraping.db"


def db_exists(output_dir):
    path = db_path(output_dir)
    return os.path.isfile(path)


def initialize(output_dir):
    path = db_path(output_dir)
    db.init(path)
    db.connect()
    db.create_tables([MWText], safe=True)


def remove_db(output_dir):
    os.remove(output_dir + os.sep + "scraping.db")
