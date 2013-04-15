import os
import re
import logging
import urllib
import urlparse
import requests

from pyramid.httpexceptions import HTTPException
from pyramid.settings import asbool

log = logging.getLogger(__name__)


_egg_info_re = re.compile(r'^([a-z0-9_.]+)-([a-z0-9_.-]+)'
                          '(\.tar\.gz|\.tar\.bz2|\.tar|\.tgz|\.zip)$',
                          re.I)


def get_egg_files(package_list):
    """
    Returns egg files from list of cached files

    :param package_list:
    """
    cached = []

    for p in package_list:
        match = _egg_info_re.match(p)
        if match:
            cached.append(match.groups(0)[1])
    return cached


def get_mimetype(file_path):
    """
    Mimetype is calculated based on the file's content. If ``_mimetype``
    attribute is available, it will be returned (backends which store
    mimetypes or can easily recognize them, should set this private
    attribute to indicate that type should *NOT* be calculated).
    """
    import mimetypes
    mtype, _encoding = mimetypes.guess_type(file_path)

    if mtype is None:
        mtype = 'application/octet-stream'

    return mtype


def url_is_egg_file(url):
    """
    Check if given url is egg compatible

    :param url:
    """
    return url is not None and (   url.lower().endswith('.zip')
                                or url.lower().endswith('.tar.gz')
                                or url.lower().endswith('.egg')
                                or url.lower().endswith('.exe')
                                or url.lower().endswith('.msi'))


def get_absolute_url(url, root_url):
    """
    Make relative URLs absolute

    >>> get_absolute_url('/src/blah.zip', 'https://awesome.org/')
    'https://awesome.org/src/blah.zip'
    >>> get_absolute_url('http://foo.bar.org/blah.zip', 'https://awesome.org/')
    'http://foo.bar.org/blah.zip'
    """
    parsed = urlparse.urlparse(url)
    if parsed.scheme:
        return url
    else:
        return urlparse.urljoin(root_url, parsed.path)


def convert_to_internal_url(external_url, package_name, filename):
    """
    Convert an external URL (i.e. not on pypi.python.org) to something
    that can be sent to the clients behind our proxy.

    Example:

    >>> convert_to_internal_url('http://foo.bar.org/src/blah-1.2.zip', 'blah', 'blah-1.2.zip')
    '../../packages/external/b/blah/blah-1.2.zip?remote=http%3A%2F%2Ffoo.bar.org%2Fsrc%2Fblah-1.2.zip'
    """
    return '../packages/external/%s/%s/%s?%s' \
        % (package_name[0], package_name, filename,
           urllib.urlencode({'remote': external_url}))


def get_links_from_html(html_body):
    """
    Extract all <a></a> links from html body

    :returns: list of dicts with links data
    :param html_body:
    """
    from HTMLParser import HTMLParser
    links = []

    class MyHTMLParser(HTMLParser):
        def handle_starttag(self, tag, attrs):
            self.context_data = {}
            if tag == 'a':
                data = dict(attrs)
                if 'href' in data:
                    data['org_href'] = data['href']
                    data['href'] = urlparse.urlparse(data['href'])
                self.context_data.update(data)

        def handle_data(self, data):
            if getattr(self, 'context_data', {}).get('href'):
                self.context_data['name'] = data

        def handle_endtag(self, tag):
            if tag == 'a' and self.context_data.get('href'):
                links.append(self.context_data)

    parser = MyHTMLParser()
    parser.feed(html_body)
    return links


def find_external_links(url):
    """
    Look for links to files in a web page and returns a set.
    """
    log.debug('Processing external sources link at %s', url)
    links = []
    response = requests.get(url)
    if response.status_code != 200:
        log.warning('Error while getting proxy info for: %s '
                    'Errors details: %s', url, response.text)
    else:
        if response.content:
            for l in get_links_from_html(response.content):
                href = l['org_href']
                if url_is_egg_file(href):
                    # href points to a filename
                    href = get_absolute_url(href, url)
                    links.append([l['name'], href])
    return links


def get_internal_pypi_links(request, package_path, package):
    packages_links = []
    if os.path.isdir(package_path):
        package_list = os.listdir(package_path)
        cached_eggs = get_egg_files(package_list)
        log.debug("versions cached for package `%s`: %s",
                  package, ', '.join(cached_eggs))
        packages_links = [(p, request.static_url(os.path.join(package_path, p)))
                          for p in package_list]
    return packages_links


def get_external_pypi_links(pypi_server, package):
    """
    Get's list of version with links to given package from given pypi_server

    :param pypi_server:
    :param package:
    """

    url = urlparse.urljoin(pypi_server, 'simple/%s' % package)
    response = requests.get(url)
    if response.status_code != 200:
        log.warning('Error while getting proxy info for: %s '
                    'Errors details: %s', package, response.text)
        raise HTTPException(response.status_code)
    content = response.content

    # create a subclass and override the handler methods
    links = []
    packages = []
    external_processed_links = set()
    for l in get_links_from_html(content):
        href = l['org_href']
        lnk_obj = l['href']

        if lnk_obj.hostname:
            # the link is to an external server.
            if lnk_obj.hostname == 'pypi.python.org':
                links.append(lnk_obj.hostname.partition('pypi.python.org')[-1])
                packages.append(l['name'])
            else:
                if l.get('rel') == 'download':
                    if url_is_egg_file(lnk_obj.path):
                        links.append(convert_to_internal_url(href, package,
                                            os.path.basename(lnk_obj.path)))
                        packages.append(l['name'])
                    else:
                        # href points to an external page where we will find
                        # links to package files, we also skip those which
                        # were already processed
                        if href not in external_processed_links:
                            for name, link in find_external_links(href):
                                links.append(convert_to_internal_url(
                                    link, package, os.path.basename(link))
                                )
                                packages.append(name)
                            external_processed_links.add(href)
        else:
            # local link to pypi.python.org
            if href.startswith('../../packages/source'):
                #convert to relative url to the server
                links.append(href.partition('../')[-1])
                packages.append(l['name'])

    return packages, links
