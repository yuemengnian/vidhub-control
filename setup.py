from setuptools import setup, find_packages

setup(
    name = "vidhub-control",
    version = "0.0.1",
    author = "Matthew Reid",
    author_email = "matt@nomadic-recording.com",
    description = "Control Smart Videohub Devices",
    packages=find_packages(exclude=['tests*']),
    include_package_data=True,
    install_requires=[
        'python-dispatch',
    ],
    platforms=['any'],
    classifiers = [
        'Development Status :: 3 - Alpha',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
    ],
)
