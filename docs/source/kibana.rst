Accessing Kibana in an Isolated Deploy
======================================

Unlike in legacy deployments, isolated deploys of this infrastructure
place Elasticsearch clusters into private subnets. Thus you cannot access
Kibana publicly and must setup an SSH tunnel. The tricky thing is that
an SSH tunnel alone is not enough - requests must be signed with the credentials
associated with an assumed IAM role. Thus an EC2 instance is needed in
a public subnet. The sentieon license server is a good template.
Once you are on the server, verify via ``curl`` that you can reach your
ES cluster's VPC endpoint.

aws-es-proxy
============

aws-es-proxy_ is a small web server that will handle
the signing of requests to AWS ES. All that is needed is an EC2 instance
with an appropriate instance profile granting access to ES. Download the
appropriate executable from Github, and run the below to start the proxy:

    ./aws-es-proxy -endpoint https://test-es-somerandomvalue.us-east-1.es.amazonaws.com

.. _aws-es-proxy: https://github.com/abutaha/aws-es-proxy

SSH Tunnel
==========

Once the proxy is running on the EC2 in the public subnet, you can return
to your local machine and add an entry to ``~/.ssh/config`` for the tunnel::

    Host <name_of_tunnel>
    HostName <public_ip_address_of_server>
    User ec2-user
    IdentitiesOnly yes
    IdentityFile <path_to_private_key>
    LocalForward 9200 127.0.0.1:9200

Then you can ssh to the tunnel with::

    ssh <name_of_tunnel> -Nv

Finally, you can then navigate to
http://localhost:9200/_plugin/kibana on your local machine and
access Kibana. Be sure to disable the ``ssh`` session once you are done, and
shut down the proxy on the EC2 as well.

Common Commands
===============

This section contains some inline commands that are useful from Kibana.
