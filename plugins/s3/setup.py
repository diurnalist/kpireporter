from setuptools import setup

setup(
    name="kpireport-s3",
    version="0.0.1",
    author="KPI Reporter LLC",
    author_email="dev@kpireporter.com",
    url="https://kpireporter.com",
    license="Prosperity Public License",
    packages=["kpireport_s3"],
    install_requires=["kpireport", "kpireport-static", "boto3"],
    entry_points={
        "kpireport.output": ["s3 = kpireport_s3:S3OutputDriver"],
    },
)
