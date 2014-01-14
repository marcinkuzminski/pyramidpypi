import os
import re
import glob
import logging
import urlparse
import requests
import hashlib

import pyramid
from pyramid.response import Response, FileResponse
from pyramid.view import view_config
from pyramid.httpexceptions import HTTPBadRequest, HTTPOk, HTTPException, HTTPNotFound

from pyramidpypi.utils import asbool, get_mimetype, get_external_pypi_links,\
    get_egg_files, get_internal_pypi_links
log = logging.getLogger(__name__)


@view_config(route_name='upload')
def upload(request):
    """Receive package from `python setup.py sdist upload -r localeggserver`"""
    settings = pyramid.threadlocal.get_current_registry().settings
    if not asbool(settings['enable_upload']):
        raise HTTPBadRequest()
    name = request.params.get('name', '').lower()
    version = request.params.get('version')
    action = request.params.get(':action')
    content = request.params.get('content')

    if not (name and version and content.file and action == 'file_upload'):
        raise HTTPBadRequest()

    path = os.path.join(settings['egg_path'], name)

    if not os.path.exists(path):
        os.makedirs(path)

    with open(os.path.join(path, content.filename), 'wb') as f:
        f.write(content.file.read())

    raise HTTPOk()


@view_config(route_name='pypi_listing', renderer='package_list.mako')
@view_config(route_name='list_all', renderer='package_list.mako')
def pypi_listing(request):
    """List all available packages eggs including different versions"""
    settings = pyramid.threadlocal.get_current_registry().settings
    egg_path = settings['egg_path']
    egg_url = settings['egg_url']
    packages_links = [(os.path.split(p)[1], '..%s%s' % (egg_url, p[len(egg_path):]))
             for p in glob.glob(os.path.join(egg_path, '*', '*'))]
    return dict(title="All available eggs", packages_links=packages_links)


@view_config(route_name='list_versions', renderer='package_list.mako')
def list_package_versions(request):
    """List available versions for :request.matchdict:`package`"""
    settings = pyramid.threadlocal.get_current_registry().settings

    # TODO: force remote should be dynamic so we don't hit pypi
    # every time we want to read package versions
    force_remote = asbool(settings['force_remote_package_index'])
    proxy_mode = asbool(settings['proxy_mode'])
    package = request.matchdict.get('package')
    packages_links = get_internal_pypi_links(request, package, settings['egg_path'])

    if proxy_mode and force_remote:
        if force_remote:
            log.debug('Force package list from pypi server')
        else:
            log.debug('Did not found package: `%s` in local repository. '
                      'Using proxy.', package)
        pypi_server = settings['pypi_server']

        try:
            _packages, _links = get_external_pypi_links(pypi_server, package)
        except HTTPException as e:
            _packages = _links = []

        if _packages and _links:
            #put remote locations into already cached results
            _cached_packages = [x[0] for x in packages_links]
            for p, l in zip(_packages, _links):
                if p not in _cached_packages:
                    packages_links += [(p, l)]

    return dict(title="All versions for {package}".format(package=package),
                packages_links=packages_links)


@view_config(route_name='list_versions_cache', renderer='package_list.mako')
def list_cached_package_versions(request):
    """List available versions for :request.matchdict:`package`"""
    settings = pyramid.threadlocal.get_current_registry().settings
    package = request.matchdict.get('package')
    packages_links = get_internal_pypi_links(request, package, settings['egg_path'])

    return dict(title="All versions for {package}".format(package=package),
                packages_links=packages_links)


@view_config(route_name='list_packages', renderer='package_list.mako')
def list_packages(request):
    """
    List available packages with link to the different versions. It's
    equivalent of calling pypi.python.org/simple
    """
    settings = pyramid.threadlocal.get_current_registry().settings
    egg_path = settings['egg_path']
    if not os.path.exists(egg_path):
        os.makedirs(egg_path)
    packages_links = sorted([(p, request.route_url('list_versions', package=p))
                      for p in os.listdir(os.path.join(egg_path))
                      if not p.startswith('.')], key=lambda e: e[0].lower())
    return dict(title="All packages", packages_links=packages_links)

@view_config(route_name='egg_url')
def egg_package(request):
    settings = pyramid.threadlocal.get_current_registry().settings
    package_parts = request.matchdict.get('package')
    package = '/'.join(package_parts)
    package_file_path = os.path.join(settings['egg_path'], package)
    if os.path.exists(package_file_path):
        return FileResponse(package_file_path, request=request, cache_max_age=3600,
                            content_type=get_mimetype(package_file_path))

    raise HTTPNotFound(request.url)

@view_config(route_name='get_package')
@view_config(route_name='get_package_h')
def get_package(request):
    settings = pyramid.threadlocal.get_current_registry().settings
    package_type = request.matchdict.get('package_type')
    letter = request.matchdict.get('letter')
    package_name = request.matchdict.get('package_name')
    package_file = request.matchdict.get('package_file')
    pypi_server = settings['pypi_server']
    log.debug('Downloading: `%s`', package_file)

    package_file_path = os.path.join(settings['egg_path'],
                                     package_name.lower(), package_file)
    if os.path.exists(package_file_path):
        log.debug('Found local file in repository for: `%s`', package_file)
        # if the file exists, then use the local file.
        response = FileResponse(package_file_path, request=request,
                                content_type=get_mimetype(package_file_path))
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
            url = urlparse.urljoin(pypi_server, 'packages/%s/%s/%s/%s'
                        % (package_type, letter, package_name, package_file))

        log.debug('Starting to download: `%s` using the url: %s',
                  package_file, url)

        pypi_response = requests.get(url, stream=True)
        log.debug('Finished downloading package: `%s`', package_file)

        if pypi_response.status_code != 200:
            log.warning('Error response while downloading for proxy: %s '
                    'Response details: %s', package_file, pypi_response.text)
            raise HTTPException(pypi_response.status_code)

        #now after we successfully downloaded the file create the package files
        package_path = os.path.join(settings['egg_path'],
                                    package_name.lower())
        if not os.path.exists(package_path):
            os.makedirs(package_path)

        #write file
        filecontent = pypi_response.raw.data
        with open(os.path.join(package_file_path), 'wb') as egg_file:
            egg_file.write(filecontent)
        log.debug('stored file %s in cache', package_file_path)
        with open(package_file_path + '.md5', 'wb') as md5_output:
            md5_output.write(hashlib.md5(filecontent).hexdigest())

        response = FileResponse(package_file_path, request=request,
                                content_type=get_mimetype(package_file_path))
        return response


## static
@view_config(route_name='robots')
def static_robots(context, request):
    _here = os.path.dirname(__file__)
    return FileResponse(os.path.join(_here, 'static', 'robots.txt'),
                        request=request, content_type='text/plain')

@view_config(route_name='favicon')
def static_favicon(context, request):
    _here = os.path.dirname(__file__)
    return FileResponse(os.path.join(_here, 'static', 'favicon.ico'),
                        request=request, content_type='image/x-icon')
