FROM mwdockerbase

COPY requirements.txt /
RUN pip3 install -r /requirements.txt

WORKDIR /services

COPY grinbase/ /usr/local/bin/grinbase/
COPY grinlib/ /usr/local/bin/grinlib/
COPY services/*.py /usr/local/bin/
COPY services/config.ini /usr/local/bin/
COPY services/config.ini /services/
COPY api/ /usr/local/bin/api/
COPY api/BGP_payout.py /content/
COPY utils/ /usr/local/bin/utils/

CMD ["/bin/sh"]
