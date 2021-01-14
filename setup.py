from setuptools import setup

setup(
    name='vbus',
    version='1.6.5',
    description='vBus client',
    long_description='vBus client',
    classifiers=[
        'Intended Audience :: Developers',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7'
    ],
    url='https://github.com/veeainc/vbus.py.git',
    author='Michael Mardinian',
    author_email='mmardinian@veea.com',
    license='To Be Define',
    packages=['vbus', 'vbus.tests'],
    install_requires=[
        'zeroconf>=0.27.0',
        'bcrypt>=3.1.7',
        'pydbus',
        'jsonschema>=3.2.0',
        'asyncio-nats-client==0.11.2',
        'genson>=1.2.1',
        'psutil>=5.7.0'
    ]
)
