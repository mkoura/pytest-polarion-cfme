from setuptools import setup

setup(
    name="pytest_polarion_cfme",
    version='0.0.1',
    packages=['pytest_polarion_cfme'],
    url="NONE",  # FIXME: once it is public
    long_description=open('README.rst').read(),
    author='Martin Kourim',
    author_email='mkourim@redhat.com',
    entry_points={
        'pytest11': [
            'pytest_polarion_cfme = pytest_polarion_cfme.plugin',
        ]
    },
    install_requires=['pytest>=2.4.2'],
    setup_requires=['setuptools_scm'],
    classifiers=['Private :: Do Not Upload'],  # hack to avoid uploading to pypi
)
