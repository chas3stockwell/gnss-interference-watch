# sam build runs this with the function directory as cwd.
# ARTIFACTS_DIR is the folder SAM zips and uploads.
build-DetectorFunction:
	mkdir -p "$(ARTIFACTS_DIR)"
	rm -rf "$(ARTIFACTS_DIR)/gnssiw"
	cp handler.py "$(ARTIFACTS_DIR)/handler.py"
	cp -R "../../shared/python/gnssiw" "$(ARTIFACTS_DIR)/gnssiw"
	pip install -r requirements.txt -t "$(ARTIFACTS_DIR)"
