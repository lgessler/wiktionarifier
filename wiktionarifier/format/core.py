import os
from collections import defaultdict

import click
import spacy
from spacy.symbols import ORTH
from bs4 import BeautifulSoup, Comment
from tqdm import tqdm
from conllu import TokenList

import wiktionarifier.scrape.db as db
from wiktionarifier.format.const import VALID_POS, NON_DEFINITION_HEADINGS
from wiktionarifier.format.exceptions import FormatException


def build_tokenizer():
    nlp = spacy.load("en_core_web_md")
    infixes = nlp.Defaults.infixes + (r"(<)",)
    nlp.tokenizer.infix_finditer = spacy.util.compile_infix_regex(infixes).finditer
    nlp.tokenizer.add_special_case(f"<a>", [{ORTH: f"<a>"}])
    nlp.tokenizer.add_special_case(f"</a>", [{ORTH: f"</a>"}])
    return nlp


def discard_empty_elements(soup, exempt=()):
    """Remove HTML elements that have no/whitespace-only content"""
    for tag in soup.find_all():
        if len(tag.get_text(strip=True)) == 0 and tag.name not in exempt:
            tag.extract()
    return soup


def discard_comments(soup):
    for tag in soup(text=lambda text: isinstance(text, Comment)):
        tag.extract()
    return soup


def discard_elements(soup, css_selectors=()):
    def depth(node):
        if node is None:
            return 0
        return 1 + depth(node.parent)

    for selector in css_selectors:
        for tag in sorted(soup.select(selector), reverse=True, key=depth):
            tag.extract()
    return soup


def excise_elements(soup, css_selectors=()):
    """
    For each css selector, get rid of them while preserving their children.
    E.g., if the css selector is "span":
        <p>Exact science based on <b><span><em><span>Cubics</span></em></span></b>,
        not on <span>theories</span>. Wisdom is Cubic testing of knowledge.</p>
    becomes
        <p>Exact science based on <b><em>Cubics</em></b>,
        not on theories. Wisdom is Cubic testing of knowledge.</p>
    inspired by: https://stackoverflow.com/questions/1765848/remove-a-tag-using-beautifulsoup-but-keep-its-contents
    """

    def depth(node):
        if node is None:
            return 0
        return 1 + depth(node.parent)

    for selector in css_selectors:
        for tag in sorted(soup.select(selector), reverse=True, key=depth):
            if getattr(tag, "parent", None):
                while len(tag.contents) > 0:
                    c = tag.contents[0]
                    tag.insert_before(c)
                tag.extract()

    return soup


def clean_html(soup):
    soup = discard_elements(
        soup,
        [
            "script",
            "style",
            "audio",
            "video",
            "hr",
            "img",
            ".interlanguage-link-target",
            "label",
            "footer",
            "nav",
            "#mw-toc-heading",
            "[class*=toclevel-]",
            ".mw-editsection",
        ],
    )
    soup = excise_elements(soup, ["head", "html", "div", "span", "b"])
    soup = discard_comments(soup)
    soup = discard_empty_elements(soup)
    return soup


def is_language_header(node):
    return node.name in ["h2", "h3"] and node.text not in NON_DEFINITION_HEADINGS and not is_pos_header(node)


def is_pos_header(node):
    return node.name in ["h3", "h4"] and node.text in VALID_POS


def remove_a_attrs(soup):
    attrs = []
    for node in soup.find_all():
        if node.name is not None and node.name == "a":
            attrs.append(node.attrs)
            node.attrs = {}
    return soup, attrs


def find_entries(tokenizer, soup):
    """
    Given parsed HTML for a wiktionary page, use heuristics to find the dictionary
    entries for each language on the page. The heuristics assume that entries
    correspond to <li> elements under an <h3> or <h4> element with a valid POS, and
    that the corresponding "parent" <h2> or <h3> tag above the POS tag has the name
    of the language. See https://en.wiktionary.org/wiki/Wiktionary:Entry_layout

    Args:
        tokenizer: spacy tokenizer that knows how to tokenize <a> and </a>
        soup: parsed page HTML

    Returns:
        dict where keys are language names and values are lists of tokenized strings
    """
    entries = defaultdict(list)

    # A list of pairs, where the first is the level of the header (1 for <h1>, etc.)
    # and the second is the BeautifulSoup node reference
    headers = []

    # keep track of whether we're currently consuming entries--while we're doing so,
    # we also need to know the header level of the POS header, the name of the language,
    # and a reference to the parent of the first <li> elements we encounter that we treat
    # as definitions
    reading_entries = False
    pos_header_level = None
    language_name = None
    li_container = None

    # depth-first traversal of the page
    for node in soup.find_all():
        tag_type = node.name

        # keep track of ALL of these headers as we traverse the document
        if tag_type in ["h2", "h3", "h4"]:
            headers.append((int(tag_type[-1]), node.text))

        # if we encounter a header that looks like a POS header, begin reading entries
        # and also note the language name, which will be the last header we read on a level
        # higher than the POS header's level. E.g. if we find <h3>Noun</h3> and our last <h2>
        # element was <h2>English</h2>, the language name is English
        if is_pos_header(node):
            reading_entries = True
            pos_header_level = int(tag_type[-1])
            parent_titles = [title for level, title in headers if level == pos_header_level - 1]
            if len(parent_titles) == 0:
                raise FormatException(
                    "Found a definition entry that does not appear to be nested under a language header"
                )
            language_name = parent_titles[-1]
        # Read definitions if the flag is set and the node is <li>
        elif reading_entries and tag_type == "li":
            # If this is the first <li> we're reading, hold a ref to its parent
            if li_container is None:
                li_container = node.parent
            # if we encounter an <li> and it does NOT share a parent with the other <li>
            # items we've seen, assume we've consumed all available definitions and bail
            # out. (This can happen if there's another list e.g. for derived terms)
            elif li_container != node.parent:
                li_container = None
                reading_entries = None
                pos_header_level = None
                continue

            # parse the inner html
            inner_content = BeautifulSoup(node.decode_contents(), features="html.parser")
            # discard all tags which are not <a>
            inner_content = excise_elements(inner_content, [":not(a[href])"])
            # to make tokenization simpler, remove attrs from all <a> elements and store them in a separate list
            inner_content, a_attrs = remove_a_attrs(inner_content)
            # get the tokens with the dehydrated <a> tags
            tokenized = tokenizer(str(inner_content).replace("</a>", " </a> ").replace("<a>", " <a> "))

            # build the list of final tokens
            tokens = []
            i = 0
            for t in tokenized:
                t = t.text
                # rehydrate <a> tags using the a_attrs list we got earlier
                if t == "<a>":
                    soup = BeautifulSoup("<a></a>", features="html.parser").find("a")
                    soup.attrs = a_attrs[i]
                    t = str(soup)[:-4]
                    i += 1
                tokens.append(t)
            # store list of tokens
            entries[language_name].append(tokens)
        # We're done reading entries if we run into a header that's at least as high as the
        # POS tag header (if not higher)
        elif (
            reading_entries
            and tag_type in [f"h{i}" for i in range(1, pos_header_level + 1)]
            and int(tag_type[-1]) == pos_header_level
        ):
            li_container = None
            reading_entries = False
            pos_header_level = None

    return entries


def format_conllu(text, entries):
    sentences = []
    for language_name, entries in sorted(entries.items(), key=lambda x: x[0]):
        for entry in entries:
            tokens = []
            href = None
            inside_link = False

            token_attrs_list = [
                {
                    "id": 0,
                    "form": token,
                    "lemma": None,
                    "upos": None,
                    "xpos": None,
                    "feats": None,
                    "head": None,
                    "deprel": None,
                    "deps": None,
                    "misc": {},
                }
                for i, token in enumerate(entry)
            ]
            token_count = 0
            for token_index, (token, token_attrs) in enumerate(zip(entry, token_attrs_list)):
                if token[:3] == "<a ":
                    href = BeautifulSoup(token + "</a>", features="html.parser").find("a").attrs["href"]
                    inside_link = True
                elif token == "</a>":
                    inside_link = False
                elif not token.isspace():
                    token_count += 1
                    token_attrs["id"] = token_count
                    if href:
                        token_attrs["misc"]["Href"] = href
                        if entry[token_index + 1] == "</a>":
                            token_attrs["misc"]["BIOLU"] = "U"
                        else:
                            token_attrs["misc"]["BIOLU"] = "B"
                        href = None
                    elif inside_link:
                        if entry[token_index + 1] == "</a>":
                            token_attrs["misc"]["BIOLU"] = "L"
                        else:
                            token_attrs["misc"]["BIOLU"] = "I"
                    else:
                        token_attrs["misc"]["BIOLU"] = "O"

                    tokens.append(token_attrs)

            token_list = TokenList(tokens)
            token_list.metadata["url"] = text.url
            token_list.metadata["language"] = language_name

            sentences.append(token_list)

    return "".join([sentence.serialize() + "\n" for sentence in sentences])


def format(input_dir, output_dir, write_individual_files=False):
    if not os.path.exists(output_dir):
        click.echo(f"Output dir {output_dir} does not exist. Creating...")
        os.makedirs(output_dir, exist_ok=True)
    db.initialize(input_dir)

    tokenizer = build_tokenizer()
    texts = db.MWText().select()
    with open(os.path.join(output_dir, "_all.conllu"), "w", encoding="utf-8") as f:
        f.write("")

    with open(os.path.join(output_dir, "_all.conllu"), "a", encoding="utf-8") as f1:
        for text in tqdm(texts):
            filepath = os.path.join(output_dir, text.file_safe_url + ".conllu")
            soup = BeautifulSoup(text.html, features="html.parser").find("body")
            soup = clean_html(soup)
            entries = find_entries(tokenizer, soup)
            conllu_string = format_conllu(text, entries)
            f1.write(conllu_string)
            with open(filepath, "w", encoding="utf-8") as f2:
                f2.write(conllu_string)
