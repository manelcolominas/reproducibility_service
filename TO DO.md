- IT SHOULD SUPPORT TO DOWNLOAD WORKFLOWS FROM ZENODO

BUT ZENODO:

Zenodo itself is blocking your internet connection — its message says: "Access to this resource has been restricted due to unusual traffic from your network."

Since even plain curl (no Python involved at all) gets the same 403, it's not something in your code — Zenodo's server is rejecting your connection before your script's logic ever runs.

- IT SHOULD ALLOW TO EXECUTE WORKFLOWS THAT THAT USES FILES BUT THEY HAD SET DATA_PERSISTENCE = FALSE
- FLAGS --appdir=  --classpath= and --log_dir= FLAGS SHOULD BE REMAPED FROM THE SUBMISSION COMMAND