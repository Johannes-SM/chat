## Installation
* create python virtual environment using requirements.txt
#### nginx
* install nginx package
* modify nginx_conf.txt to include your domain
* add the text in nginx_conf.txt to /etc/nginx/nginx.conf
* reload nginx using `nginx -s reload` if nginx is already running
#### postgres db
* follow  https://wiki.archlinux.org/title/PostgreSQL#Installation until you've setup a database
* run `generate_tables.sql` file in your database as a superuser (psql -d database_name -f generate_tables.sql)

## Run
* execute `persistent_server.py`
* pass arguments as needed
