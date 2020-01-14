from setuptools import setup

setup(
    name='vbus',
    version='0.1.0',
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
    url='https://vbus@bitbucket.org/vbus/vbus.py.git',
    author='Michael Mardinian',
    author_email='mmardinian@veea.com',
    license='To Be Define',
    packages=['vbus'],
    install_requires=[
        'zeroconf',
        'bcrypt',
        'pydbus',
        'jsonschema',
        'asyncio-nats-client',
        'genson'
    ],
)
