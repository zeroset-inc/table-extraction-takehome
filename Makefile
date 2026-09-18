.PHONY: build test score clean

build:            ## regenerate cases, packets, views, evidence and gold
	python3 kit/build.py
	python3 kit/build.py --held-out
	cd validator && cargo build

test:             ## the geometric rules, as executable examples
	cd validator && cargo test

score:            ## score answers/ against gold/
	python3 kit/score.py answers/

clean:
	rm -f cases/*.xlsx cases/*.json cases/*.html gold/*.json
