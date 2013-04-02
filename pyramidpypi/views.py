import os
import re
import glob
import logging
import urlparse
import requests
import hashlib

import pyramid
from pyramid.response import Response
from pyramid.view import view_config
from pyramid.httpexceptions import HTTPBadRequest, HTTPOk, HTTPException

from pyramidpypi.utils import asbool, get_mimetype, get_external_pypi_links,\
    get_egg_files
log = logging.getLogger(__name__)


@view_config(route_name='upload')
def upload(request):
    """Receive package from `python setup.py sdist upload -r localeggserver`"""
    settings = pyramid.threadlocal.get_current_registry().settings

    name = request.params.get('name', '').lower()
    version = request.params.get('version')
    action = request.params.get(':action')
    content = request.params.get('content')

    if not (name and version and content.file and action == 'file_upload'):
        raise HTTPBadRequest()

    path = os.path.join(settings['egg_path'], name)

    if not os.path.exists(path):
        os.makedirs(path)

    open(os.path.join(path, content.filename), 'wb').write(content.file.read())

    raise HTTPOk()


@view_config(route_name='pypi_listing', renderer='package_list.mako')
@view_config(route_name='list_all', renderer='package_list.mako')
def pypi_listing(request):
    """List all available packages eggs including different versions"""
    settings = pyramid.threadlocal.get_current_registry().settings

    egg_path = settings['egg_path']
    egg_url = settings['egg_url']
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
    settings = pyramid.threadlocal.get_current_registry().settings
    egg_path = settings['egg_path']
    proxy_mode = asbool(settings['proxy_mode'])
    package = request.matchdict.get('package')
    package_path = os.path.join(egg_path, package)

    if proxy_mode and (not os.path.isdir(package_path) or force_remote):
        if force_remote:
            log.debug('Force package list from pypi server')
        else:
            log.debug('Did not found package: `%s` in local repository. '
                      'Using proxy.' % (package))
        pypi_server = settings['pypi_server']

        try:
            packages, links = get_external_pypi_links(pypi_server, package)
        except HTTPException as e:
            packages = links = []

    else:
        package_list = os.listdir(package_path)
        cached_eggs = get_egg_files(package_list)
        log.debug("versions cached for package `%s`: %s"
                  % (package, ', '.join(cached_eggs)))
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
    settings = pyramid.threadlocal.get_current_registry().settings
    egg_path = settings['egg_path']
    if not os.path.exists(egg_path):
        os.makedirs(egg_path)
    packages = os.listdir(os.path.join(egg_path))
    links = [request.route_url('list_versions', package=p) for p in packages]

    return dict(title="All packages", links=links, packages=packages)


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
        package_path = os.path.join(settings['egg_path'],
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
