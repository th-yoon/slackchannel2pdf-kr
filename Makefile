appname = slackchannel2pdf
package = slackchannel2pdf

help:
	@echo "Makefile for $(appname)"

coverage:
	coverage run -m unittest discover && coverage html && coverage report

pylint:
	pylint $(package)

check_complexity:
	flake8 $(package) --max-complexity=10

flake8:
	flake8 $(package) --count

deploy:
	rm dist/*
	python setup.py sdist
	twine upload dist/*
