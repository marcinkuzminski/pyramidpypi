import os

from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.rst')).read()
CHANGES = open(os.path.join(here, 'CHANGES.rst')).read()

requires = [
    'pyramid==1.4.0',
    'pyramid_debugtoolbar',
    'waitress==0.8.2',
    'requests==1.2.0'
]

setup(name='pyramidpypi',
      version='0.4',
      description=('pyramidpypi - a very simply pypi server and '
                   'proxy written in pyramid'),
      long_description=README + '\n\n' + CHANGES,
      classifiers=[
        "Programming Language :: Python",
        "Framework :: Pylons",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
        ],
      author='Daniel Kraus, Marcin Kuzminski',
      author_email='dakra@tr0ll.net',
      url='https://github.com/dakra/pyramidpypi',
      keywords='web pyramid pylons pypi proxy',
      packages=find_packages(),
      include_package_data=True,
      zip_safe=False,
      install_requires=requires,
      tests_require=requires,
      test_suite="pyramidpypi",
      license='ISC',
      entry_points="""\
      [paste.app_factory]
      main = pyramidpypi:main
      """,
      )
