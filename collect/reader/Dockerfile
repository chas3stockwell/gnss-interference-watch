# Reader container image.
#
# The zip skeleton in the SAM template is enough for the stub. Switch the
# Reader to this image when netCDF/BUFR decoding lands — those libraries do
# not fit a small zip. Build from the repository root:
#
#   docker build -f collect/reader/Dockerfile -t gnssiw-reader .
#
# Then set the function's PackageType to Image and point Metadata at this
# file (DockerContext is the repo root). See README, "Switching the Reader
# to a container image".

FROM public.ecr.aws/lambda/python:3.12

COPY collect/reader/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY collect/reader/handler.py ${LAMBDA_TASK_ROOT}/handler.py
COPY shared/python/gnssiw ${LAMBDA_TASK_ROOT}/gnssiw

CMD ["handler.handler"]
