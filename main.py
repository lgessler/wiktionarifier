import click
import wiktionarifier.scrape.core as sc


@click.group()
def top():
    pass


@click.command(help="Scrape entries from wiktionary for use as training data.")
@click.option('--output-dir', default='data/scraped', help='directory for scraping output')
@click.option('--wiktionary-language', default='en', help='Language in which definitions are written on Wiktionary')
@click.option('--strategy', default='random', type=click.Choice(['inorder', 'random'], case_sensitive=False),
              help="Method for deciding which Wiktionary pages to visit. `inorder` visits all pages in lexicographic "
                   "order, while `random` will sample them randomly.")
@click.option('--max-pages', default=50000, help="Stop scraping after collecting this number of pages")
@click.option('--overwrite/--no-overwrite', default=False, help="If true, discard all previous scraping results")
def scrape(output_dir, wiktionary_language, strategy, max_pages, overwrite):
    if not overwrite or (overwrite and click.confirm('Are you SURE you want to discard previous scraping results?')):
        sc.scrape(output_dir, wiktionary_language, strategy, max_pages, overwrite)


top.add_command(scrape)

if __name__ == '__main__':
    top()