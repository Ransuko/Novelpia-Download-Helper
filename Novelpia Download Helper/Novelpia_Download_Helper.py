import requests
import os
import json
import re
import logging
import html
import time
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import tkinter as tk
from tkinter import messagebox, filedialog
from tkinter import ttk

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

class NovelpiaDownloader:
    def __init__(self, novel_id, loginkey, download_folder, download_interval):
        self.novel_id = novel_id
        self.loginkey = loginkey
        self.download_folder = download_folder
        self.download_interval = download_interval
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Cookie': f'LOGINKEY={loginkey}'
        })

    def get_chapter_list(self):
        chapters = []
        page = 0
        seen_chapter_ids = set()
        consecutive_duplicate_pages = 0
        max_consecutive_duplicate_pages = 3
        chapter_number = 1  # Initialize chapter number

        while True:
            url = f"https://novelpia.com/proc/episode_list"
            data = {
                'novel_no': self.novel_id,
                'sort': 'DOWN',
                'page': page
            }
            try:
                logging.debug(f"Requesting chapter list page {page}")
                response = self.session.post(url, data=data)
                logging.debug(f"Response status code: {response.status_code}")
                response.raise_for_status()
                
                chapter_matches = re.findall(r'id="bookmark_(\d+)"></i>(.+?)</b>', response.text)
                
                logging.debug(f"Found {len(chapter_matches)} chapter matches on page {page}")
                
                if not chapter_matches:
                    logging.info("No more chapters found. Ending chapter list retrieval.")
                    break

                new_chapters_on_page = False
                for chapter_id, chapter_title in chapter_matches:
                    if chapter_id not in seen_chapter_ids:
                        seen_chapter_ids.add(chapter_id)
                        new_chapters_on_page = True
                        
                        chapter_title = html.unescape(chapter_title.strip())
                        
                        chapters.append({'id': chapter_id, 'title': chapter_title, 'number': chapter_number})
                        logging.debug(f"Added chapter: Number {chapter_number}, ID {chapter_id}, Title: {chapter_title}")
                        chapter_number += 1  # Increment chapter number

                if new_chapters_on_page:
                    consecutive_duplicate_pages = 0
                else:
                    consecutive_duplicate_pages += 1
                    logging.warning(f"No new chapters found on page {page}. Consecutive duplicate pages: {consecutive_duplicate_pages}")

                if consecutive_duplicate_pages >= max_consecutive_duplicate_pages:
                    logging.info(f"Reached {max_consecutive_duplicate_pages} consecutive duplicate pages. Ending chapter list retrieval.")
                    break

                page += 1
            except requests.RequestException as e:
                logging.error(f"Error fetching chapter list: {e}")
                break

        logging.info(f"Total unique chapters found: {len(chapters)}")
        return chapters

    def download_chapter(self, chapter):
        url = f"https://novelpia.com/proc/viewer_data/{chapter['id']}"
        try:
            response = self.session.get(url)
            response.raise_for_status()
            logging.debug(f"Response status code for chapter {chapter['id']}: {response.status_code}")
            
            data = response.json()
            
            if 's' in data and isinstance(data['s'], list):
                chapter_content = []
                for item in data['s']:
                    text = item.get('text', '')
                    text = html.unescape(text)
                    
                    text = text.replace('&nbsp;&nbsp;', '\n\n')
                    text = text.replace('&nbsp;', '\n')
                    
                    paragraphs = text.split('\n')
                    
                    for para in paragraphs:
                        soup = BeautifulSoup(para, 'html.parser')
                        for img in soup.find_all('img', class_='cover-img'):
                            img_url = urljoin('https://novelpia.com', img['src'])
                            img_filename = f"chapter_{chapter['number']}_cover.jpg"
                            self.download_image(img_url, img_filename)
                            chapter_content.append(f"[Cover Image: {img_filename}]\n")
                        processed_text = soup.get_text().strip()
                        if processed_text:
                            chapter_content.append(processed_text + '\n')

                chapter_text = '\n'.join(chapter_content)
                chapter_text = re.sub(r'\n{3,}', '\n\n', chapter_text)
                chapter_text = f"Chapter {chapter['number']}: {chapter['title']}\n\n" + chapter_text

                chapter_dir = os.path.join(self.download_folder, 'chapters')
                os.makedirs(chapter_dir, exist_ok=True)

                filename = f"{chapter['number']:04d}_{self.sanitize_filename(chapter['title'])}.txt"
                filepath = os.path.join(chapter_dir, filename)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(chapter_text)
                logging.info(f"Successfully downloaded and saved chapter {chapter['number']}: {chapter['title']}")
            else:
                logging.error(f"Unexpected response format for chapter {chapter['id']}")
                logging.debug(f"Raw response: {response.text[:500]}...")
        except requests.RequestException as e:
            logging.error(f"Error downloading chapter {chapter['id']}: {e}")
        except json.JSONDecodeError as e:
            logging.error(f"Error parsing JSON for chapter {chapter['id']}: {e}")
            logging.debug(f"Raw response: {response.text[:500]}...")

    def download_image(self, img_url, img_filename):
        try:
            img_response = self.session.get(img_url)
            img_response.raise_for_status()
            img_filepath = os.path.join(self.download_folder, 'images', img_filename)
            os.makedirs(os.path.dirname(img_filepath), exist_ok=True)
            with open(img_filepath, 'wb') as img_file:
                img_file.write(img_response.content)
            logging.info(f"Successfully downloaded image: {img_filename}")
        except requests.RequestException as e:
            logging.error(f"Error downloading image {img_filename}: {e}")

    def compile_novel(self, chapters):
        novel_content = []
        for chapter in chapters:
            filename = f"{chapter['number']:04d}_{self.sanitize_filename(chapter['title'])}.txt"
            filepath = os.path.join(self.download_folder, 'chapters', filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    chapter_content = f.read()
                novel_content.append(chapter_content)
                logging.info(f"Added chapter {chapter['number']} to compilation: {chapter['title']}")
            except FileNotFoundError:
                logging.warning(f"Chapter file not found: {filepath}")

        if not novel_content:
            logging.error("No chapters were found for compilation.")
            return

        novel_filename = f"{self.novel_id}_complete.txt"
        novel_filepath = os.path.join(self.download_folder, novel_filename)
        with open(novel_filepath, 'w', encoding='utf-8') as f:
            f.write('\n\n'.join(novel_content))
        logging.info(f"Compiled novel saved to {novel_filepath}")

    @staticmethod
    def sanitize_filename(filename):
        return re.sub(r'[\\/*?:"<>|]', '', filename)

class NovelpiaDownloaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Novelpia Downloader")

        # Create main frame
        main_frame = ttk.Frame(root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Input fields
        input_frame = ttk.Frame(main_frame)
        input_frame.pack(fill=tk.X, pady=5)

        ttk.Label(input_frame, text="Novel ID:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.entry_novel_id = ttk.Entry(input_frame)
        self.entry_novel_id.grid(row=0, column=1, sticky="we", padx=5, pady=5)

        ttk.Label(input_frame, text="LOGINKEY:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.entry_loginkey = ttk.Entry(input_frame)
        self.entry_loginkey.grid(row=1, column=1, sticky="we", padx=5, pady=5)
        ttk.Button(input_frame, text="Load Cookie", command=self.load_cookie).grid(row=1, column=2, padx=5, pady=5)  # Add this button

        ttk.Label(input_frame, text="Download Folder:").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        self.entry_download_folder = ttk.Entry(input_frame)
        self.entry_download_folder.grid(row=2, column=1, sticky="we", padx=5, pady=5)
        ttk.Button(input_frame, text="Browse", command=self.browse_folder).grid(row=2, column=2, padx=5, pady=5)

        ttk.Label(input_frame, text="Download Interval (seconds):").grid(row=3, column=0, sticky="w", padx=5, pady=5)
        self.entry_download_interval = ttk.Entry(input_frame)
        self.entry_download_interval.grid(row=3, column=1, sticky="we", padx=5, pady=5)

        input_frame.columnconfigure(1, weight=1)

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=5)

        ttk.Button(button_frame, text="List Chapters", command=self.list_chapters).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Download Selected Chapters", command=self.download_selected_chapters).pack(side=tk.LEFT, padx=5)

        # Chapter list with scrollbar
        list_frame = ttk.Frame(main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.chapter_listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED)
        self.chapter_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.chapter_listbox.bind("<Shift-Button-1>", self.mouse_select)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.chapter_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.chapter_listbox.config(yscrollcommand=scrollbar.set)

        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=5)

        # Action log
        log_frame = ttk.Frame(main_frame)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        ttk.Label(log_frame, text="Action Log:").pack(anchor="w")
        self.log_text = tk.Text(log_frame, height=10, wrap=tk.WORD)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        log_scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=log_scrollbar.set)

        self.chapters = []  # Store the full chapter list

    def browse_folder(self):
        folder_selected = filedialog.askdirectory()
        self.entry_download_folder.delete(0, tk.END)
        self.entry_download_folder.insert(0, folder_selected)

    def load_cookie(self):
        # Open file dialog to select cookie.json
        cookie_file = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")])
        if not cookie_file:
            return

        # Load and parse the cookie.json file
        try:
            with open(cookie_file, 'r', encoding='utf-8') as f:
                cookies = json.load(f)

            # Extract the LOGINKEY
            login_key = None
            for cookie in cookies:
                if cookie.get('name') == 'LOGINKEY':
                    login_key = cookie.get('value')
                    break

            if login_key:
                self.entry_loginkey.delete(0, tk.END)
                self.entry_loginkey.insert(0, login_key)
                self.log_action("LOGINKEY loaded from cookie.json")
            else:
                messagebox.showerror("Error", "LOGINKEY not found in the cookie file.")

        except (json.JSONDecodeError, FileNotFoundError) as e:
            messagebox.showerror("Error", f"Failed to load cookie file: {e}")

    def list_chapters(self):
        novel_id = self.entry_novel_id.get()
        loginkey = self.entry_loginkey.get()

        if not novel_id or not loginkey:
            messagebox.showerror("Missing Information", "Please fill out Novel ID and LOGINKEY.")
            return

        self.log_action("Fetching chapter list...")
        downloader = NovelpiaDownloader(novel_id, loginkey, "", 0)
        self.chapters = downloader.get_chapter_list()

        self.chapter_listbox.delete(0, tk.END)
        for chapter in self.chapters:
            self.chapter_listbox.insert(tk.END, f"{chapter['number']:04d} - {chapter['title']}")
        
        self.log_action(f"Found {len(self.chapters)} chapters.")

    def mouse_select(self, event):
        self.chapter_listbox.selection_anchor(tk.ACTIVE)
        self.chapter_listbox.selection_set(tk.ACTIVE)
        return "break"

    def download_selected_chapters(self):
        novel_id = self.entry_novel_id.get()
        loginkey = self.entry_loginkey.get()
        download_folder = self.entry_download_folder.get()
        try:
            download_interval = float(self.entry_download_interval.get())
        except ValueError:
            messagebox.showerror("Invalid Input", "Download interval must be a number.")
            return

        if not novel_id or not loginkey or not download_folder:
            messagebox.showerror("Missing Information", "Please fill out all fields.")
            return

        selected_indices = self.chapter_listbox.curselection()
        selected_chapters = [self.chapters[i] for i in selected_indices]

        if not selected_chapters:
            messagebox.showerror("No Chapters Selected", "Please select chapters to download.")
            return

        downloader = NovelpiaDownloader(novel_id, loginkey, download_folder, download_interval)
        downloaded_chapters = []
        total_chapters = len(selected_chapters)

        for i, chapter in enumerate(selected_chapters, 1):
            self.log_action(f"Downloading chapter {chapter['number']}: {chapter['title']}")
            downloader.download_chapter(chapter)
            downloaded_chapters.append(chapter)
            progress = (i / total_chapters) * 100
            self.progress_var.set(progress)
            self.root.update_idletasks()
            time.sleep(download_interval)

        self.log_action("Compiling novel...")
        downloader.compile_novel(downloaded_chapters)
        self.log_action("Novel download and compilation complete!")
        messagebox.showinfo("Download Complete", "Novel download and compilation complete!")

    def log_action(self, message):
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

if __name__ == "__main__":
    root = tk.Tk()
    gui = NovelpiaDownloaderGUI(root)
    root.mainloop()