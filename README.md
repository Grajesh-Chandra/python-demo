# python-demo

demo app for python

reload .env

> find . -type f -name "\*.pyc" -delete
> find . -type d -name "**pycache**" -exec rm -r {} +

> source .env
> flask run --debug

find . -type f -name "\*.pyc" -delete && find . -type d -name "**pycache**" -exec rm -r {} + && source .env && flask run --debug -p 8010