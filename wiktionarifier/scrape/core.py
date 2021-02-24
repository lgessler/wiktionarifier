import os
import requests as R
import click

import wiktionarifier.scrape.db as db


def process_page(page):
    mediawiki_link = str(page)
    if db.mwtext_exists(mediawiki_link):
        return page.full_url(), True
    title = page.title()
    url = page.full_url()
    file_safe_url = page.title(as_filename=True)
    latest_revision = page.latest_revision
    rev_id = str(latest_revision["revid"])
    text = latest_revision["text"]
    oldest_revision_time = page.oldest_revision.timestamp.isoformat()
    latest_revision_time = latest_revision.timestamp.isoformat()

    response = R.get(page.full_url())
    if response.status_code != 200:
        raise R.HTTPError(f'Non-200 response from wiktionary: {response.status_code}')
    html = response.content
    db.add_text(
        mediawiki_link,
        url,
        rev_id,
        text,
        html,
        title,
        file_safe_url,
        oldest_revision_time,
        latest_revision_time,
    )
    return url, False
    

def scrape(output_dir, wiktionary_language, strategy, max_pages, overwrite):
    import pywikibot
    site = pywikibot.Site(code=wiktionary_language, fam="wiktionary")
    site.login()

    if not os.path.exists(output_dir):
        click.echo(f"Output dir {output_dir} does not exist. Creating...")
        os.makedirs(output_dir, exist_ok=True)

    if overwrite:
        click.echo(f"Removing existing database at {db.db_path(output_dir)}...")
        db.remove_db(output_dir)
    click.echo(f"Initializing connection to database at {db.db_path(output_dir)}")
    db.initialize(output_dir)
    count = db.mwtext_count()
    click.echo(f"Initialized connection with {count} existing records.")

    if strategy == 'inorder':
        last_visited = db.get_last_modified()
        if last_visited is not None:
            click.echo(f"Resuming scraping session beginning from {last_visited.url}...")
        pages = site.allpages(start=last_visited.title if last_visited is not None else '!')
    elif strategy == 'random':
        pages = site.randompages()
    else:
        raise Exception(f"Unknown scraping strategy: `{strategy}`")

    for page in pages:
        url, already_seen = process_page(page)
        if already_seen:
            click.echo(f"Already saw {url}, skipping")
        else:
            click.echo(f"Processed {url}")
            count += 1
        if count >= max_pages:
            click.echo(f"Maximum page count {max_pages} reached, quitting")
            break
