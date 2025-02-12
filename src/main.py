import logging
import re
import textwrap
from urllib.parse import urljoin

import requests_cache
from tqdm import tqdm

from configs import configure_argument_parser, configure_logging
from constants import BASE_DIR, MAIN_DOC_URL, PEP, EXPECTED_STATUS
from exceptions import ParserFindTagException
from outputs import control_output
from utils import find_tag, get_soup_from_url


def whats_new(session):
    whats_new_url = urljoin(MAIN_DOC_URL, 'whatsnew/')
    soup = get_soup_from_url(session, whats_new_url)
    main_div = find_tag(soup, 'section', attrs={'id': 'what-s-new-in-python'})
    div_with_ul = find_tag(main_div, 'div', attrs={'class': 'toctree-wrapper'})
    sections_by_python = div_with_ul.find_all(
        'li', attrs={'class': 'toctree-l1'})
    results = [('Ссылка на статью', 'Заголовок', 'Редактор, автор')]

    for section in tqdm(sections_by_python):
        version_a_tag = find_tag(section, 'a')
        href = version_a_tag['href']
        version_link = urljoin(whats_new_url, href)
        soup = get_soup_from_url(session, version_link)
        h1 = find_tag(soup, 'h1')
        dl = find_tag(soup, 'dl')
        dl_text = dl.text.replace('\n', ' ')
        results.append((version_link, h1.text, dl_text))

    return results


def latest_versions(session):
    soup = get_soup_from_url(session, MAIN_DOC_URL)
    sidebar = find_tag(soup, 'div', attrs={'class': 'sphinxsidebarwrapper'})
    ul_tags = sidebar.find_all('ul')

    for ul in ul_tags:
        if 'All versions' in ul.text:
            a_tags = ul.find_all('a')
            break
    else:
        raise ParserFindTagException('Ничего не нашлось')

    results = [('Ссылка на документацию', 'Версия', 'Статус')]
    pattern = r'Python (?P<version>\d\.\d+) \((?P<status>.*)\)'

    for a_tag in a_tags:
        link = a_tag['href']
        text_match = re.search(pattern, a_tag.text)
        if text_match is not None:
            version, status = text_match.groups()
        else:
            version, status = a_tag.text, ''
        results.append(
            (link, version, status)
        )

    return results


def download(session):
    downloads_url = urljoin(MAIN_DOC_URL, 'download.html')
    soup = get_soup_from_url(session, downloads_url)
    main_tag = find_tag(soup, 'div', attrs={'role': 'main'})
    table_tag = find_tag(main_tag, 'table', attrs={'class': 'docutils'})
    pdf_a4_tag = find_tag(table_tag, 'a',
                          attrs={'href': re.compile(r'.+pdf-a4\.zip$')})
    pdf_a4_link = pdf_a4_tag['href']
    archive_url = urljoin(downloads_url, pdf_a4_link)
    filename = archive_url.split('/')[-1]
    downloads_dir = BASE_DIR / 'downloads'
    downloads_dir.mkdir(exist_ok=True)
    archive_path = downloads_dir / filename
    response = session.get(archive_url)

    with open(archive_path, 'wb') as file:
        file.write(response.content)

    logging.info(f'Архив был загружен и сохранён: {archive_path}')


def pep(session):
    soup = get_soup_from_url(session, PEP)
    expected_status_flat = sum(EXPECTED_STATUS.values(), ())
    statuses = {}

    tr_tags = find_tag(
        soup,
        'section',
        attrs={'id': 'index-by-category'}
    ).find_all('tr')

    logs_list = []

    for tag in tqdm(tr_tags):
        if tag.find('abbr'):
            general_abbr_text = tag.find('abbr').text
            preview_status = general_abbr_text[1:]
            pep_url = urljoin(PEP, find_tag(tag, 'a')['href'])
            soup = get_soup_from_url(session, pep_url)
            page_abbr_text = find_tag(soup, 'abbr').text

            if page_abbr_text not in expected_status_flat:
                page_abbr_text = 'Unknown status'

            statuses[page_abbr_text] = statuses.get(page_abbr_text, 0) + 1

            try:
                if page_abbr_text not in EXPECTED_STATUS[preview_status]:
                    logs_list.append(
                        textwrap.dedent(f'''\
                        Несовпадающий статус:
                        {pep_url}
                        Статус в карточке: {page_abbr_text}
                        Ожидаемые статусы: {EXPECTED_STATUS[preview_status]}'''
                                        )
                    )
            except KeyError:
                logs_list.append(
                    f'Недопустимый статус {preview_status} на странице '
                    f'с общим списком PEP для объекта {pep_url}!'
                )

    logging.warning('\n'.join(logs_list))
    results = [('Статус', 'Количество')]
    results.extend((status, statuses[status]) for status in sorted(statuses))
    results.append(('Total', sum(statuses.values())))
    return results


MODE_TO_FUNCTION = {
    'whats-new': whats_new,
    'latest-versions': latest_versions,
    'download': download,
    'pep': pep,
}


def main():
    configure_logging()
    logging.info('Парсер запущен!')
    arg_parser = configure_argument_parser(MODE_TO_FUNCTION.keys())
    args = arg_parser.parse_args()
    logging.info(f'Аргументы командной строки: {args}')
    session = requests_cache.CachedSession()

    if args.clear_cache:
        session.cache.clear()

    parser_mode = args.mode
    results = MODE_TO_FUNCTION[parser_mode](session)

    if results is not None:
        control_output(results, args)

    logging.info('Парсер завершил работу.')


if __name__ == '__main__':
    main()
