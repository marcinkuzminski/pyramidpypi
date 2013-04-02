import os
import re
import glob
import logging
import urllib
import urlparse
import requests
import hashlib

from pyramid.response import Response
from pyramid.view import view_config
from pyramid.httpexceptions import HTTPBadRequest, HTTPOk, HTTPNotFound, \
    HTTPException
from pyramid.settings import asbool

log = logging.getLogger(__name__)


def get_mimetype(file_path):
    """
    Mimetype is calculated based on the file's content. If ``_mimetype``
    attribute is available, it will be returned (backends which store
    mimetypes or can easily recognize them, should set this private
    attribute to indicate that type should *NOT* be calculated).
    """
    import mimetypes
    mtype, encoding = mimetypes.guess_type(file_path)

    if mtype is None:
        mtype = 'application/octet-stream'

    return mtype


def url_is_egg_file(url):
    return url is not None and (   url.lower().endswith('.zip')
                                or url.lower().endswith('.tar.gz')
                                or url.lower().endswith('.egg')
                                or url.lower().endswith('.exe')
                                or url.lower().endswith('.msi'))


def get_absolute_url(url, root_url):
    """Make relative URLs absolute

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
            if getattr(self, 'context_data', {}):
                    self.context_data['name'] = data

        def handle_endtag(self, tag):
            if tag == 'a' and self.context_data:
                links.append(self.context_data)

    parser = MyHTMLParser()
    parser.feed(html_body)
    return links


def find_external_links(url):
    """
    Look for links to files in a web page and returns a set.
    """
    log.debug('Processing extenrnal sources link at %s' % (url))
    links = []
    response = requests.get(url)
    if response.status_code != 200:
        log.warning('Error while getting proxy info for: %s'
                           'Errors details: %s', url,
                           response.text)
    else:
        if response.content:
            for l in get_links_from_html(response.content):
                print l
                href = l['org_href']
                if url_is_egg_file(href):
                    # href points to a filename
                    href = get_absolute_url(href, url)
                    links.append([l['name'], href])
    return links


def _get_external_pypi_links(pypi_server, package):
    """
    Get's list of version with links to given package from given pypi_server

    :param pypi_server:
    :param package:
    """

    url = urlparse.urljoin(pypi_server, 'simple/%s' % package)
    response = requests.get(url)
    if response.status_code != 200:
        log.warning('Error while getting proxy info for: %s'
                    'Errors details: %s' % (package, response.text))
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
                                links.append(convert_to_internal_url(link, package,
                                                    os.path.basename(link)))
                                packages.append(name)
                            external_processed_links.add(href)
        else:
            # local link to pypi.python.org
            if href.startswith('../../packages/source'):
                #convert to relative url to the server
                links.append(href.partition('../')[-1])
                packages.append(l['name'])

    return packages, links


@view_config(route_name='upload')
def upload(request):
    """Receive package from `python setup.py sdist upload -r localeggserver`"""

    name = request.params.get('name', '').lower()
    version = request.params.get('version')
    action = request.params.get(':action')
    content = request.params.get('content')

    if not (name and version and content.file and action == 'file_upload'):
        raise HTTPBadRequest()

    path = os.path.join(request.registry.settings['egg_path'], name)

    if not os.path.exists(path):
        os.makedirs(path)

    open(os.path.join(path, content.filename), 'wb').write(content.file.read())

    raise HTTPOk()


@view_config(route_name='pypi_listing', renderer='package_list.mako')
@view_config(route_name='list_all', renderer='package_list.mako')
def pypi_listing(request):
    """List all available packages eggs including different versions"""

    egg_path = request.registry.settings['egg_path']
    egg_url = request.registry.settings['egg_url']
    packages = glob.glob(os.path.join(egg_path, '*', '*'))
    links = ['..%s%s' % (egg_url, p[len(egg_path):]) for p in packages]
    packages = [os.path.split(p)[1] for p in packages]

    return dict(title="All available eggs", links=links, packages=packages)


@view_config(route_name='list_versions', renderer='package_list.mako')
def list_versions(request):
    """List available versions for :request.matchdict:`package`"""
    # TODO: force remote should be dynamic so we don't hit pypi
    # everytime we want to read package versions
    force_remote = True
    egg_path = request.registry.settings['egg_path']
    proxy_mode = asbool(request.registry.settings['proxy_mode'])
    package = request.matchdict.get('package')
    package_path = os.path.join(egg_path, package)

    if proxy_mode and (not os.path.isdir(package_path) or force_remote):
        if force_remote:
            log.debug('Force package list from pypi server')
        else:
            log.debug('Did not found package: `%s` in local repository. '
                      'Using proxy.' % (package))
        pypi_server = request.registry.settings['pypi_server']
        packages, links = _get_external_pypi_links(pypi_server, package)

    else:
        _egg_info_re = re.compile(r'^([a-z0-9_.]+)-([a-z0-9_.-]+)'
                                  '(\.tar\.gz|\.tar\.bz2|\.tar|\.tgz|\.zip)$',
                                  re.I)
        cached_vers = []
        package_list = os.listdir(package_path)
        for p in package_list:
            match = _egg_info_re.match(p)
            if match:
                cached_vers.append(match.groups(0)[1])
        log.debug("versions cached for package `%s`: %s"
                  % (package, ', '.join(cached_vers)))
        packages = package_list
        links = [request.static_url(os.path.join(package_path, p))
                 for p in packages]

    return dict(title="All versions for {package}".format(package=package),
                links=links, packages=packages)


@view_config(route_name='list_packages', renderer='package_list.mako')
def list_packages(request):
    """
    List available packages with link to the different versions. It's
    equivalent of calling pypi.python.org/simple
    """

    egg_path = request.registry.settings['egg_path']
    if not os.path.exists(egg_path):
        os.makedirs(egg_path)
    packages = os.listdir(os.path.join(egg_path))
    links = [request.route_url('list_versions', package=p) for p in packages]

    return dict(title="All packages", links=links, packages=packages)


@view_config(route_name='get_package')
@view_config(route_name='get_package_h')
def get_package(request):
    package_type = request.matchdict.get('package_type')
    letter = request.matchdict.get('letter')
    package_name = request.matchdict.get('package_name')
    package_file = request.matchdict.get('package_file')
    pypi_server = request.registry.settings['pypi_server']
    log.debug('Downloading: `%s`', package_file)

    package_file_path = os.path.join(request.registry.settings['egg_path'],
                                     package_name, package_file)
    if os.path.exists(package_file_path):
        log.debug('Found local file in repository for: `%s`', package_file)
        # if the file exists, then use the local file.
        response = Response(content_type=get_mimetype(package_file_path))
        response.app_iter = open(package_file_path, 'rb')
        return response
    else:
        # Downloads the egg from pypi and saves it locally, then
        # it will return it.
        remote = request.GET.get('remote')
        if remote:
            # the requested link is not on pypi.python.org, we need to use
            # the remote URL
            url = remote
        else:
            url = urlparse.urljoin(pypi_server,
                            'packages/%s/%s/%s/%s'
                        % (package_type, letter, package_name, package_file))

        log.debug('Starting to download: `%s` using the url: %s'
                  % (package_file, url))

        pypi_response = requests.get(url, stream=True)
        log.debug('Finished downloading package: `%s`', package_file)

        if pypi_response.status_code != 200:
            log.warning('Error response while downloading for proxy: %s'
                    'Response details: %s', package_file, pypi_response.text)
            raise HTTPException(pypi_response.status_code)

        #now after we successfully downloaded the file create the package files
        package_path = os.path.join(request.registry.settings['egg_path'],
                                    package_name)
        if not os.path.exists(package_path):
            os.makedirs(package_path)

        #write file
        filecontent = pypi_response.raw.data
        with open(os.path.join(package_file_path), 'wb') as egg_file:
            egg_file.write(filecontent)
        log.debug('stored file %s in cache' % (package_file_path))
        with open(package_file_path + '.md5', 'wb') as md5_output:
            md5_output.write(hashlib.md5(filecontent).hexdigest())

        response = Response(content_type=get_mimetype(package_file_path))
        response.app_iter = open(package_file_path, 'rb')
        return response
