from setuptools import setup

setup(
    name='pytest_polarion_cfme',
    version='0.1.0',
    url='https://github.com/mkoura/pytest-polarion-cfme',
    description='pytest plugin for collecting test cases and recording test results',
    long_description=open('README.rst').read().strip(),
    author='Martin Kourim',
    author_email='mkourim@redhat.com',
    license='GPL',
    py_modules=['pytest_polarion_cfme'],
    install_requires=['pytest>=2.4.2'],
    entry_points={'pytest11': ['pytest_polarion_cfme = pytest_polarion_cfme']},
    keywords='py.test pytest',
    classifiers=['Private :: Do Not Upload'],  # hack to avoid uploading to pypi
)
