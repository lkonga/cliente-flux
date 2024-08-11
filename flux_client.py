import asyncio
import aiohttp
import os
import json
import sqlite3
from datetime import datetime
import fal_client
import argparse

# SQLite setup
def setup_database():
    conn = sqlite3.connect('prompts.db')
    return conn

def initialize_database():
    conn = sqlite3.connect('prompts.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS prompts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp TEXT,
                  prompt_content TEXT,
                  project_name TEXT,
                  result_data TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS prompt_templates
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  template_name TEXT UNIQUE,
                  prompt_content TEXT)''')
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

def store_prompt_template(conn, template_name, prompt_content):
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO prompt_templates (template_name, prompt_content) VALUES (?, ?)",
              (template_name, prompt_content))
    conn.commit()
    return c.lastrowid

def load_prompt_template(conn, template_name):
    c = conn.cursor()
    c.execute("SELECT prompt_content FROM prompt_templates WHERE template_name = ?", (template_name,))
    result = c.fetchone()
    return result[0] if result else None

def print_templates(conn):
    c = conn.cursor()
    c.execute("SELECT template_name, prompt_content FROM prompt_templates")
    templates = c.fetchall()
    if templates:
        print("Existing templates:")
        for template in templates:
            print(f"- {template[0]}: {template[1]}")
    else:
        print("No templates found.")

def delete_prompt_template(conn, template_name):
    c = conn.cursor()
    c.execute("DELETE FROM prompt_templates WHERE template_name = ?", (template_name,))
    conn.commit()
    if c.rowcount > 0:
        print(f"Template '{template_name}' has been deleted.")
    else:
        print(f"No template found with name '{template_name}'.")

def insert_prompt(conn, timestamp, prompt_content, project_name, result_data):
    c = conn.cursor()
    c.execute("INSERT INTO prompts (timestamp, prompt_content, project_name, result_data) VALUES (?, ?, ?, ?)",
              (timestamp, prompt_content, project_name, json.dumps(result_data)))
    conn.commit()
    return c.lastrowid

async def download_image(url, project_name, base_filename):
    output_dir = "output"
    project_dir = os.path.join(output_dir, project_name)
    os.makedirs(project_dir, exist_ok=True)

    index = 0
    while True:
        if index == 0:
            filename = os.path.join(project_dir, base_filename)
        else:
            name, ext = os.path.splitext(base_filename)
            filename = os.path.join(project_dir, f"{name}_{index}{ext}")

        if not os.path.exists(filename):
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        with open(filename, 'wb') as f:
                            f.write(await response.read())
                        print(f"Image saved as {filename}")
                        return filename
                    else:
                        print(f"Failed to download image. Status code: {response.status}")
                        return None
        index += 1

async def submit(args):
    conn = setup_database()

    if args.add_template:
        user_prompt = input("Enter your prompt template: ")
        store_prompt_template(conn, args.add_template, user_prompt)
        print(f"Prompt template '{args.add_template}' has been stored.")
        conn.close()
        return

    if args.template:
        user_prompt = load_prompt_template(conn, args.template)
        if not user_prompt:
            print(f"No template found with name '{args.template}'")
            conn.close()
            return
        default_project_name = args.template
    else:
        user_prompt = input("Enter your prompt for image generation: ")
        default_project_name = "default"

    project_name = input(f"Enter the project name (default: {default_project_name}): ") or default_project_name

    handler = await fal_client.submit_async(
        "fal-ai/flux-pro",
        arguments={
            "prompt": user_prompt,
            "resolution": "landscape_4_3",
            "quality_tokens": ["high quality", "ultra-detailed", "4K resolution"],
            "style_tokens": ["photorealistic"],
            "num_inference_steps": 50,
        },
    )

    log_index = 0
    async for event in handler.iter_events(with_logs=True):
        if isinstance(event, fal_client.InProgress):
            new_logs = event.logs[log_index:]
            for log in new_logs:
                print(log["message"])
            log_index = len(event.logs)

    result = await handler.get()
    print(result)

    # Download and save the generated image
    if result and 'images' in result and result['images']:
        image_url = result['images'][0]['url']
        filename = await download_image(image_url, project_name, 'generated_image_hd.jpg')

        # Insert prompt data into SQLite
        timestamp = datetime.now().isoformat()
        prompt_id = insert_prompt(conn, timestamp, user_prompt, project_name, result)
        print(f"Prompt data saved with ID: {prompt_id}")

    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Flux Client for image generation")
    parser.add_argument("--add-template", type=str, help="Add a new prompt template")
    parser.add_argument("--template", type=str, help="Use a stored prompt template")
    parser.add_argument("--db-init", action="store_true", help="Initialize the database")
    parser.add_argument("--templates", action="store_true", help="Print existing templates")
    parser.add_argument("--delete-template", type=str, help="Delete a prompt template")
    args = parser.parse_args()

    if args.db_init:
        initialize_database()
    elif args.templates:
        conn = setup_database()
        print_templates(conn)
        conn.close()
    elif args.delete_template:
        conn = setup_database()
        delete_prompt_template(conn, args.delete_template)
        conn.close()
    else:
        asyncio.run(submit(args))
