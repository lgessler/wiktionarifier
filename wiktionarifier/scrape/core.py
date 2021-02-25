import os
import requests as R
import click

import wiktionarifier.scrape.db as db


def process_page(page):
    if not any(' lemma' in cat.title().lower() for cat in page.categories()) \
            or any('non-lemma' in cat.title().lower() for cat in page.categories()):
        click.secho("\tPage doesn't appear to be a lemma, skipping", fg="yellow")
        return page.full_url(), True
    mediawiki_link = str(page)
    if db.mwtext_exists(mediawiki_link):
        return page.full_url(), True
    title = page.title()
    url = page.full_url()
    if "%3A" in url:
        click.secho("\tPage doesn't look like a page with dictionary entries, skipping", fg="yellow")
        return page.full_url(), True
    file_safe_url = page.title(as_filename=True)
    latest_revision = page.latest_revision
    rev_id = str(latest_revision["revid"])
    text = latest_revision["text"]
    oldest_revision_time = page.oldest_revision.timestamp.isoformat()
    latest_revision_time = latest_revision.timestamp.isoformat()

    response = R.get(page.full_url())
    if response.status_code != 200:
        click.secho(f"\tNon-200 response from wiktionary: {response.status_code}", fg="red")
        return page.full_url(), True
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
        count = db.mwtext_count()
        if count >= max_pages:
            click.secho(f"Maximum page count {max_pages} reached, quitting", fg="green")
            break
        url, skipped = process_page(page)
        if skipped:
            click.secho(f"[{count}/{max_pages}] Skipping {url}", fg="yellow")
        else:
            click.secho(f"[{count}/{max_pages}] Processed {url}", dim=True)

