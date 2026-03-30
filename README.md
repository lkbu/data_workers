# data_workers

# VM set up

Prepare the VM

    Create a new VM in Proxmox.

    Install Ubuntu Server.

    Install Docker and Docker Compose:

```
sudo apt update && sudo apt install docker.io docker-compose -y
sudo usermod -aG docker $USER
# Log out and log back in for group changes to take effect
```

### Installing modern docker engine

```
# Add Docker's official GPG key:
sudo apt update
sudo apt install ca-certificates curl gnupg -y
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin -y

```

### Launch Prefect Server

Prefect 3.0 (the latest) is best run via a simple docker-compose.yml. This will host the UI and the database (PostgreSQL) where your schedules are stored.

Create a directory called prefect and add this docker-compose.yml:

```
services:
  database:
    image: postgres:15-alpinel
    restart: always
    environment:
      POSTGRES_USER: prefect
      POSTGRES_PASSWORD: yourpassword
      POSTGRES_DB: prefect
    volumes:
      - db_data:/var/lib/postgresql/data

  server:
    image: prefecthq/prefect:3-latest
    restart: always
    volumes:
      - ./:/opt/prefect
    entrypoint: ["prefect", "server", "start"]
    environment:
      - PREFECT_API_DATABASE_CONNECTION_URL=postgresql+asyncpg://prefect:yourpassword@database:5432/prefect
      - PREFECT_SERVER_API_HOST=0.0.0.0
    ports:
      - "4200:4200"

volumes:
  db_data:
  ```

Run docker-compose up -d. You can now access the Prefect UI at http://<your-vm-ip>:4200.

### Writing and Deploying your Script

You don't just "upload" a script to Prefect; you deploy it. Here is a simple example of a custom script:

```# my_script.py
from prefect import flow, task

@task
def say_hello():
    print("Hello from Proxmox!")

@flow(log_prints=True)
def my_home_flow():
    say_hello()

if __name__ == "__main__":
    # This creates a deployment on the server
    my_home_flow.serve(name="proxmox-deployment", 
                      cron="0 * * * *") # Runs every hour
```

### Other

```
sudo apt update
# Install the venv module and the pip installer
sudo apt install python3-venv python3-pip -y
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.14 python3.14-venv python3.14-dev -y
```
## SSH to VM

### Prepare the VM (Inside Proxmox Console)

Open the Proxmox web GUI, select your VM, and click Console. Log in with the credentials you created during installation.
Install & Enable SSH

Ubuntu Server usually installs SSH by default, but let's make sure it's active and through the firewall:

```
sudo apt update
sudo apt install openssh-server -y

# Enable the firewall and allow SSH
sudo ufw allow ssh
sudo ufw enable
```

### connect

```
# Replace 'username' and 'ip-address' with yours
ssh username@192.168.1.50
```

### Pro Tip: Set Up SSH Keys (No More Passwords)

Typing a password every time you want to check your Prefect logs gets old fast. Plus, it’s significantly more secure.
On your LOCAL machine (Laptop):

Generate a modern, high-security key:

```
ssh-keygen -t ed25519
# Just hit Enter through the prompts

ssh-copy-id username@192.168.1.50
```



# prefect set up

Create dir
```
sudo mkdir -p /opt/prefect

# Replace 'username' with your actual Ubuntu username
sudo chown -R $USER:$USER /opt/prefect

cd /opt/prefect
nano docker-compose.yml
```
Paste your YAML content, then press Ctrl+O, Enter, and Ctrl+X to save and exit.

Test:

```
cd /opt/prefect

docker compose up -d
```

if errors out:
```
# 1. Create the docker group (usually already exists)
sudo groupadd docker

# 2. Add your current user to the group
sudo usermod -aG docker $USER

# 3. Apply the group changes to your current session 
# (This saves you from having to log out and back in)
newgrp docker
```




# docker set up

## Modern 

```
# Add Docker's official GPG key:
sudo apt update
sudo apt install ca-certificates curl gnupg -y
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin -y
```

```
services:
  database:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: prefect
      POSTGRES_PASSWORD: your_secure_password
      POSTGRES_DB: prefect
    volumes:
      - prefect_db:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U prefect"]
      interval: 10s
      timeout: 5s
      retries: 5

  server:
    image: prefecthq/prefect:3-latest
    command: prefect server start
    environment:
      - PREFECT_API_DATABASE_CONNECTION_URL=postgresql+asyncpg://prefect:your_secure_password@database:5432/prefect
      - PREFECT_SERVER_API_HOST=0.0.0.0
      - PREFECT_SERVER_UI_API_URL=http://<YOUR_VM_IP>:4200/api
      - PREFECT_SERVER_API_CORS_ALLOWED_ORIGINS=http://<YOUR_VM_IP>:4200
    ports:
      - "4200:4200"
    depends_on:
      database:
        condition: service_healthy

  # This worker lives inside the same VM and waits for work
  worker:
    image: prefecthq/prefect:3-latest
    command: prefect worker start --pool 'my-proxmox-pool'
    environment:
      - PREFECT_API_URL=http://server:4200/api
    depends_on:
      - server

volumes:
  prefect_db:
```




## direct set up

Log in to your Proxmox VM via SSH. We will create a permanent home for your code and its environment

```
# Create the project directory
sudo mkdir -p /opt/prefect/my-project
sudo chown -R $USER:$USER /opt/prefect/my-project
cd /opt/prefect/my-project

# Clone your repo (use the dot to clone into the current folder)
git clone https://github.com/yourusername/your-repo.git .

# Create the static virtual environment
python3 -m venv .venv

# Manually update/install dependencies
source .venv/bin/activate
pip install --upgrade pip
pip install prefect pandas sqlalchemy psycopg2-binary  # and whatever else is in your requirements
```

### The Auto-Sync Mechanism (GitHub to VM)

Since you want the VM to update whenever the master branch changes, the simplest and most reliable "Home Lab" method is a small shell script triggered by a cron job.

Create the sync script: nano /opt/prefect/sync_code.sh
```
#!/bin/bash
cd /opt/prefect/my-project
git fetch origin master
git reset --hard origin/master
```

Make it executable and schedule it:

```
chmod +x /opt/prefect/sync_code.sh
# Open crontab
crontab -e
# Add this line to check for updates every 5 minutes
*/5 * * * * /opt/prefect/sync_code.sh
```

### Setting up the Process Worker

Your Prefect Server is in Docker, but your code is on the "Metal." We need to run a Process Worker on the Ubuntu OS.

    Create a "Process" Work Pool in the Prefect UI:

        Go to Work Pools > Create +.

        Select Process as the type.

        Name it proxmox-process-pool.

    Start the Worker on the VM OS:
    You want this worker to run in the background. We will use nohup for testing, but eventually, you should use a systemd service.

```
source /opt/prefect/my-project/.venv/bin/activate
# Point the worker to the Server API (which is on localhost port 4200)
export PREFECT_API_URL="http://127.0.0.1:4200/api"

nohup prefect worker start --pool "proxmox-process-pool" > worker.log 2>&1 &
```

### Handling Modular Imports (Subfolders)

Since your project has subfolders, we need to ensure Python can see them. We do this by setting the PYTHONPATH in the prefect.yaml.

Your prefect.yaml (on your laptop):

```
name: my-process-project
prefect-version: 3.x

deployments:
- name: "process-data-fetcher"
  entrypoint: "main_flow.py:main_flow"
  work_pool:
    name: "proxmox-process-pool"
  # This tells the worker WHERE the code is on the VM disk
  job_variables:
    # This ensures the worker doesn't try to download code; it looks in this folder
    working_dir: "/opt/prefect/my-project"
    # This handles your subfolder dependencies
    env:
      PYTHONPATH: "/opt/prefect/my-project"
```

### How to Deploy & Schedule

From your laptop, inside your project folder:

    Set the API URL to your VM's IP:
    export PREFECT_API_URL="http://<VM_IP>:4200/api"

    Run the deployment:
    prefect deploy --name process-data-fetcher

### How it works

You Code: You push a change to master on GitHub.

VM Syncs: Within 5 minutes, your cron job pulls the new code into /opt/prefect/my-project.

Prefect Triggers: The schedule hits. The Process Worker (already running on the VM) sees the job.

Execution: The Worker goes to the folder /opt/prefect/my-project, activates the .venv, and runs python main_flow.py.

Why this is better for testing:

    Speed: No Docker images to build or push. Changes are live in 5 minutes.

    Persistence: Your .venv is static. If you need a new library, just SSH in once, pip install it, and it's there forever.

    Debugging: You can see the actual files on the VM disk if something goes wrong.

Would you like the systemd configuration file next? (This will make sure your Prefect Worker starts automatically if your Proxmox VM reboots).