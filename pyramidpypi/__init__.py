from pyramid.config import Configurator


def main(global_config, **settings):
    """
    This function returns a Pyramid WSGI application.
    """
    config = Configurator(settings=settings)


    # maybe someday I'll add nicer templates?
    config.add_static_view('static', 'static', cache_max_age=3600)
    config.add_route('favicon', '/favicon.ico', request_method='GET')
    config.add_route('robots', '/robots.txt', request_method='GET')

    config.add_route('egg_url', settings['egg_url']+'*package')
    config.add_route('list_packages', '/', request_method='GET')
    config.add_route('upload', '/', request_method='POST')

    config.add_route('pypi_listing', '/pypi/')
    config.add_route('list_all', '/egg-index/')

    config.add_route('list_versions_cache', '/c/{package}/')
    config.add_route('list_versions', '/{package}/')
    #config.add_route('get_version', '/{package}/{version}')

    config.add_route('get_package', '/packages/{package_type}/{letter}/{package_name}/{package_file}',
                     request_method='GET')
    config.add_route('get_package_h', '/packages/{package_type}/{letter}/{package_name}/{package_file}',
                     request_method='HEAD')
    # config.add_view(context='pyramid.exceptions.NotFound',
    #                 view='pyramid.view.append_slash_notfound_view')
    config.scan()
    return config.make_wsgi_app()
