from setuptools import setup, find_packages

setup(
    name='ckanext-orgreport',
    version='2.0.0',
    description='CKAN Organization Email Report (uses ckanext-report IReport)',
    packages=find_packages(),
    namespace_packages=['ckanext'],
    entry_points='''
        [ckan.plugins]
        orgreport=ckanext.orgreport.plugin:OrgReportPlugin
    ''',
    install_requires=[
        'ckanext-report',
    ],
    include_package_data=True,
    zip_safe=False,
)
