FROM nikolaik/python-nodejs:python3.8-nodejs10

# Declare environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

ENV VIRTUAL_ENV=/opt/venv \
    KOBOCAT_LOGS_DIR=/srv/logs \
    DJANGO_SETTINGS_MODULE=onadata.settings.prod \
    # The mountpoint of a volume shared with the `nginx` container. Static files will
    # be copied there.
    NGINX_STATIC_DIR=/srv/static \
    KOBOCAT_SRC_DIR=/srv/src/kobocat \
    BACKUPS_DIR=/srv/backups \
    TMP_DIR=/srv/tmp \
    UWSGI_USER=kobo \
    UWSGI_GROUP=kobo \
    SERVICES_DIR=/etc/service \
    CELERY_PID_DIR=/var/run/celery \
    INIT_PATH=/srv/init

# Install Dockerize
ENV DOCKERIZE_VERSION v0.6.1
RUN wget https://github.com/jwilder/dockerize/releases/download/$DOCKERIZE_VERSION/dockerize-linux-amd64-$DOCKERIZE_VERSION.tar.gz -P /tmp \
    && tar -C /usr/local/bin -xzvf /tmp/dockerize-linux-amd64-$DOCKERIZE_VERSION.tar.gz \
    && rm /tmp/dockerize-linux-amd64-$DOCKERIZE_VERSION.tar.gz

# Create needed directories
RUN mkdir -p ${NGINX_STATIC_DIR} && \
    mkdir -p ${KOBOCAT_SRC_DIR} && \
    mkdir -p ${TMP_DIR} && \
    mkdir -p ${BACKUPS_DIR} && \
    mkdir -p ${CELERY_PID_DIR} && \
    mkdir -p ${SERVICES_DIR}/uwsgi && \
    mkdir -p ${SERVICES_DIR}/uwsgi_wrong_port_warning && \
    mkdir -p ${SERVICES_DIR}/celery && \
    mkdir -p ${SERVICES_DIR}/celery_beat && \
    mkdir -p ${KOBOCAT_LOGS_DIR}/ && \
    mkdir -p ${KOBOCAT_SRC_DIR}/emails && \
    mkdir -p ${INIT_PATH}

# Install `apt` packages.
RUN curl -sS https://dl.yarnpkg.com/debian/pubkey.gpg | apt-key add -

RUN apt-get -qq update && \
    apt-get -qq -y install \
        gdal-bin \
        libproj-dev \
        gettext \
        postgresql-client \
        libsqlite3-mod-spatialite \
        openjdk-11-jre \
        locales \
        runit-init \
        rsync \
        less \
        vim \
        gosu \
        cron && \
    apt-get clean && \
        rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Install locales
RUN echo 'en_US.UTF-8 UTF-8' > /etc/locale.gen && \
    locale-gen && dpkg-reconfigure locales -f noninteractive

# Create local user UWSGI_USER`
RUN adduser --disabled-password --gecos '' "$UWSGI_USER"

# Copy KoBoCAT directory
COPY . "${KOBOCAT_SRC_DIR}"

# Install `pip` packages
RUN virtualenv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN pip install  --quiet --upgrade pip && \
    pip install  --quiet pip-tools
COPY ./dependencies/pip/prod.txt "${TMP_DIR}/pip_dependencies.txt"
RUN pip-sync "${TMP_DIR}/pip_dependencies.txt" 1>/dev/null && \
    rm -rf ~/.cache/pip

# Using `/etc/profile.d/` as a repository for non-hard-coded environment variable overrides.
RUN echo "export PATH=${PATH}" >> /etc/profile && \
    echo 'source /etc/profile' >> /root/.bashrc && \
    echo 'source /etc/profile' >> /home/${UWSGI_USER}/.bashrc

# Remove getty* services to avoid errors of absent tty at sv start-up
RUN rm -rf /etc/runit/runsvdir/default/getty-tty*

# Create symlinks for runsv services
RUN ln -s "${KOBOCAT_SRC_DIR}/docker/run_uwsgi_wrong_port_warning.bash" "${SERVICES_DIR}/uwsgi_wrong_port_warning/run" && \
    ln -s "${KOBOCAT_SRC_DIR}/docker/run_uwsgi.bash" "${SERVICES_DIR}/uwsgi/run" && \
    ln -s "${KOBOCAT_SRC_DIR}/docker/run_celery.bash" "${SERVICES_DIR}/celery/run" && \
    ln -s "${KOBOCAT_SRC_DIR}/docker/run_celery_beat.bash" "${SERVICES_DIR}/celery_beat/run"

# Add/Restore `UWSGI_USER`'s permissions
RUN chown -R ":${UWSGI_GROUP}" ${CELERY_PID_DIR} && \
    chmod g+w ${CELERY_PID_DIR} && \
    chown -R "${UWSGI_USER}:${UWSGI_GROUP}" ${KOBOCAT_SRC_DIR}/emails/ && \
    chown -R "${UWSGI_USER}:${UWSGI_GROUP}" ${KOBOCAT_LOGS_DIR} && \
    chown -R "${UWSGI_USER}:${UWSGI_GROUP}" ${TMP_DIR} && \
    chown -R "${UWSGI_USER}:${UWSGI_GROUP}" ${VIRTUAL_ENV} && \
    chown -R "${UWSGI_USER}:${UWSGI_GROUP}" ${BACKUPS_DIR}

WORKDIR "${KOBOCAT_SRC_DIR}"

# TODO: Remove port 8000, say, at the start of 2021 (see kobotoolbox/kobo-docker#301 and wrong port warning above)
EXPOSE 8001 8000

CMD ["/bin/bash", "-c", "exec ${KOBOCAT_SRC_DIR}/docker/init.bash"]
