PyramidPyPI
===========

This is a very simple pypi-like server written with the pyramid web framework.
It also has a builtin download proxy, which in case package is not found
will download it from location that official pypi server points to, and store
for later usage.

Installation
------------
Download the git repository and do ``python setup.py install``.

You can configure the server by editing the ``production.ini`` and then
just start the http server with ``pserve production.ini`` or refer to
the `pyramid docs <http://readthedocs.org/docs/pyramid/en/latest/>`_
for other deployment options.

Usage
-----

Add your local egg server to you ``~/.pypirc``::

    [distutils]
    index-servers =
        pypi
        local

    [pypi]
    username: pypi_user
    password: pypi_pass
    repository: http://pypi.python.org/pypi

    [pyramidpypi]
    username: local_user
    password: local_pass
    repository: http://127.0.0.1:6543/

.. note::

    `pyramidpypi` has no authentication build-in, so username&password is
    only relevant if the pypi folder is served from a webserver and that server
    has ACLs in place to access the eggs.

Now you can simply upload your add with::

    python setup.py sdist upload -r pyramidpypi

And to install a package from it, simply do::

    pip install -i http://127.0.0.1:6543/ <your package>
