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
from io import BytesIO
from PIL import Image, ImageTk
import threading
import queue

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

class NovelpiaDownloader:
    def __init__(self, novel_id, cookies, download_folder, download_interval, gui_logger):
        self.novel_id = novel_id
        self.cookies = cookies
        self.download_folder = download_folder
        self.download_interval = download_interval
        self.gui_logger = gui_logger
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        self.session.cookies.update(self.cookies)
        self.novel_info = {}

    def get_novel_info(self):
        url = f"https://novelpia.com/novel/{self.novel_id}"
        try:
            response = self.session.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
        
            # Extract title
            title_element = soup.select_one('.epnew-novel-title')
            self.novel_info['title'] = title_element.text.strip() if title_element else "Unknown Title"
        
            # Extract cover image URL
            cover_element = soup.select_one('.epnew-cover-box img.cover_img')
            self.novel_info['cover_url'] = cover_element['src'] if cover_element else None
        
            # Extract synopsis
            synopsis_element = soup.select_one('.synopsis')
            self.novel_info['synopsis'] = synopsis_element.text.strip() if synopsis_element else "No synopsis available"
        
            # Extract additional info (you can add more as needed)
            self.novel_info['likes'] = soup.select_one('.like-box .like-cnt').text.strip() if soup.select_one('.like-box .like-cnt') else "Unknown"
            self.novel_info['views'] = soup.select_one('.view-box .view-cnt').text.strip() if soup.select_one('.view-box .view-cnt') else "Unknown"
        
            self.gui_logger(f"Successfully retrieved novel info for: {self.novel_info['title']}")
            return self.novel_info
        except requests.RequestException as e:
            error_message = f"[ERROR] Error fetching novel info: {e}"
            logging.error(error_message)
            self.gui_logger(error_message)
            return None

    def get_chapter_list(self):
        chapters = []
        page = 0
        seen_chapter_ids = set()
        consecutive_duplicate_pages = 0
        max_consecutive_duplicate_pages = 3
        chapter_number = 1

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
                        chapter_number += 1

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
                error_message = f"[ERROR] Error fetching chapter list: {e}"
                logging.error(error_message)
                self.gui_logger(error_message)
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

                if not chapter_text.strip():
                    raise ValueError("Chapter content is empty")

                self.save_chapter(chapter, chapter_text)
                self.gui_logger(f"Successfully downloaded and saved chapter {chapter['number']}: {chapter['title']}")
            else:
                raise ValueError(f"Unexpected response format for chapter {chapter['id']}")
        except requests.RequestException as e:
            self.handle_download_error(chapter, f"Error downloading chapter: {e}")
        except json.JSONDecodeError as e:
            self.handle_download_error(chapter, f"Error parsing JSON: {e}")
        except ValueError as e:
            self.handle_download_error(chapter, str(e))

    def handle_download_error(self, chapter, error_message):
        error_log = f"[ERROR] Chapter {chapter['number']}: {chapter['title']} - {error_message}"
        logging.error(error_log)
        self.gui_logger(error_log)
        placeholder_content = f"Chapter {chapter['number']}: {chapter['title']}\n\n[ERROR] This chapter could not be downloaded. Error: {error_message}"
        self.save_chapter(chapter, placeholder_content, is_error=True)

    def save_chapter(self, chapter, content, is_error=False):
        chapter_dir = os.path.join(self.download_folder, 'chapters')
        os.makedirs(chapter_dir, exist_ok=True)

        prefix = "ERROR_" if is_error else ""
        filename = f"{prefix}{chapter['number']:04d}_{self.sanitize_filename(chapter['title'])}.txt"
        filepath = os.path.join(chapter_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        if is_error:
            self.gui_logger(f"[ERROR] Saved placeholder for failed chapter {chapter['number']}: {chapter['title']}")

    def download_image(self, img_url, img_filename):
        try:
            img_response = self.session.get(img_url)
            img_response.raise_for_status()
            img_filepath = os.path.join(self.download_folder, 'images', img_filename)
            os.makedirs(os.path.dirname(img_filepath), exist_ok=True)
            with open(img_filepath, 'wb') as img_file:
                img_file.write(img_response.content)
            self.gui_logger(f"Successfully downloaded image: {img_filename}")
        except requests.RequestException as e:
            error_message = f"[ERROR] Error downloading image {img_filename}: {e}"
            logging.error(error_message)
            self.gui_logger(error_message)

    def compile_novel(self, chapters):
        novel_content = []
        for chapter in chapters:
            prefix = "ERROR_"
            filename = f"{prefix}{chapter['number']:04d}_{self.sanitize_filename(chapter['title'])}.txt"
            filepath = os.path.join(self.download_folder, 'chapters', filename)
        
            if not os.path.exists(filepath):
                filename = f"{chapter['number']:04d}_{self.sanitize_filename(chapter['title'])}.txt"
                filepath = os.path.join(self.download_folder, 'chapters', filename)

            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    chapter_content = f.read()
                novel_content.append(chapter_content)
                self.gui_logger(f"Added chapter {chapter['number']} to compilation: {chapter['title']}")
            except FileNotFoundError:
                error_message = f"[ERROR] Chapter file not found: {filepath}"
                logging.warning(error_message)
                self.gui_logger(error_message)

        if not novel_content:
            error_message = "[ERROR] No chapters were found for compilation."
            logging.error(error_message)
            self.gui_logger(error_message)
            return

        novel_filename = f"{self.novel_id}_complete.txt"
        novel_filepath = os.path.join(self.download_folder, novel_filename)
        with open(novel_filepath, 'w', encoding='utf-8') as f:
            f.write('\n\n'.join(novel_content))
        self.gui_logger(f"Compiled novel saved to {novel_filepath}")

    @staticmethod
    def sanitize_filename(filename):
        return re.sub(r'[\\/*?:"<>|]', '', filename)

class NovelpiaDownloaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Novelpia Download Helper")
        self.root.geometry("1600x900")
        
        self.queue = queue.Queue()
        self.thread = None
        # Create main frame
        main_frame = ttk.Frame(root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Input fields
        input_frame = ttk.Frame(main_frame)
        input_frame.pack(fill=tk.X, pady=5)

        ttk.Label(input_frame, text="Novel ID:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.entry_novel_id = ttk.Entry(input_frame)
        self.entry_novel_id.grid(row=0, column=1, sticky="we", padx=5, pady=5)

        ttk.Label(input_frame, text="Cookies (JSON):").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.text_cookies = tk.Text(input_frame, height=5, width=50)
        self.text_cookies.grid(row=1, column=1, sticky="we", padx=5, pady=5)
        ttk.Button(input_frame, text="Load Cookies", command=self.load_cookies).grid(row=1, column=2, padx=5, pady=5)

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

        ttk.Button(button_frame, text="Fetch Novel Info & List Chapters", command=self.fetch_novel_info_and_chapters).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Download Selected Chapters", command=self.download_selected_chapters).pack(side=tk.LEFT, padx=5)

        # Novel Info Frame
        self.novel_info_frame = ttk.Frame(main_frame)
        self.novel_info_frame.pack(fill=tk.X, pady=5)

        # Cover Image
        self.cover_label = ttk.Label(self.novel_info_frame)
        self.cover_label.grid(row=0, column=0, rowspan=4, padx=5, pady=5)

        # Novel Info Labels
        self.title_label = ttk.Label(self.novel_info_frame, text="Title: ")
        self.title_label.grid(row=0, column=1, sticky="w", padx=5, pady=2)

        # Synopsis
        ttk.Label(self.novel_info_frame, text="Synopsis:").grid(row=0, column=2, sticky="nw", padx=5, pady=2)
        self.synopsis_text = tk.Text(self.novel_info_frame, height=4, wrap=tk.WORD)
        self.synopsis_text.grid(row=1, column=2, sticky="nsew", padx=5, pady=2)
        self.synopsis_text.config(state=tk.DISABLED)

        self.novel_info_frame.columnconfigure(1, weight=1)
        self.novel_info_frame.rowconfigure(4, weight=1)

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
        self.log_text.tag_configure("error", foreground="red")

        log_scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=log_scrollbar.set)

        self.chapters = []  # Store the full chapter list

    def fetch_novel_info_and_chapters(self):
        novel_id = self.entry_novel_id.get()
        cookies_json = self.text_cookies.get("1.0", tk.END)

        if not novel_id or not cookies_json:
            messagebox.showerror("Missing Information", "Please fill out Novel ID and Cookies.")
            return

        try:
            cookies = json.loads(cookies_json)
            cookies_dict = {cookie['name']: cookie['value'] for cookie in cookies}
        except json.JSONDecodeError:
            messagebox.showerror("Invalid JSON", "The cookies JSON is not valid.")
            return

        self.thread = threading.Thread(target=self._fetch_novel_info_and_chapters_thread, args=(novel_id, cookies_dict))
        self.thread.start()
        self.root.after(100, self.process_queue)

    def _fetch_novel_info_and_chapters_thread(self, novel_id, cookies):
        downloader = NovelpiaDownloader(novel_id, cookies, "", 0, self.queue_log_action)
        novel_info = downloader.get_novel_info()

        if novel_info:
            self.queue.put(("update_novel_info", novel_info))
            self.queue_log_action("Novel information fetched successfully.")
            
            # Fetch chapter list
            chapters = downloader.get_chapter_list()
            self.queue.put(("update_chapter_list", chapters))
        else:
            self.queue_log_action("[ERROR] Failed to fetch novel information.")

    def update_novel_info(self, novel_info):
        self.title_label.config(text=f"Title: {novel_info['title']}")

        self.synopsis_text.config(state=tk.NORMAL)
        self.synopsis_text.delete(1.0, tk.END)
        self.synopsis_text.insert(tk.END, novel_info['synopsis'])
        self.synopsis_text.config(state=tk.DISABLED)

        if novel_info['cover_url']:
            self.load_cover_image(novel_info['cover_url'])

    def load_cover_image(self, url):
        try:
            # Add scheme if it's missing
            if url.startswith('//'):
                url = 'https:' + url
            elif not url.startswith(('http://', 'https://')):
                url = urljoin('https://novelpia.com', url)

            response = requests.get(url)
            img_data = BytesIO(response.content)
            img = Image.open(img_data)
            img.thumbnail((150, 200))  # Resize the image
            photo = ImageTk.PhotoImage(img)
            self.cover_label.config(image=photo)
            self.cover_label.image = photo  # Keep a reference
        except Exception as e:
            self.log_action(f"[ERROR] Failed to load cover image: {e}")

    def update_chapter_list(self):
        self.chapter_listbox.delete(0, tk.END)
        for chapter in self.chapters:
            self.chapter_listbox.insert(tk.END, f"{chapter['number']:04d} - {chapter['title']}")
        
        self.log_action(f"Found {len(self.chapters)} chapters.")

    def browse_folder(self):
        folder_selected = filedialog.askdirectory()
        self.entry_download_folder.delete(0, tk.END)
        self.entry_download_folder.insert(0, folder_selected)

    def load_cookies(self):
        file_path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if file_path:
            with open(file_path, 'r') as file:
                self.text_cookies.delete('1.0', tk.END)
                self.text_cookies.insert(tk.END, file.read())

    def mouse_select(self, event):
        self.chapter_listbox.selection_anchor(tk.ACTIVE)
        self.chapter_listbox.selection_set(tk.ACTIVE)
        return "break"

    def download_selected_chapters(self):
        novel_id = self.entry_novel_id.get()
        cookies_json = self.text_cookies.get("1.0", tk.END)
        download_folder = self.entry_download_folder.get()
        try:
            download_interval = float(self.entry_download_interval.get())
        except ValueError:
            messagebox.showerror("Invalid Input", "Download interval must be a number.")
            return

        if not novel_id or not cookies_json or not download_folder:
            messagebox.showerror("Missing Information", "Please fill out all fields.")
            return

        try:
            cookies = json.loads(cookies_json)
            cookies_dict = {cookie['name']: cookie['value'] for cookie in cookies}
        except json.JSONDecodeError:
            messagebox.showerror("Invalid JSON", "The cookies JSON is not valid.")
            return

        selected_indices = self.chapter_listbox.curselection()
        selected_chapters = [self.chapters[i] for i in selected_indices]

        if not selected_chapters:
            messagebox.showerror("No Chapters Selected", "Please select chapters to download.")
            return

        self.thread = threading.Thread(target=self._download_selected_chapters_thread, 
                                       args=(novel_id, cookies_dict, download_folder, download_interval, selected_chapters))
        self.thread.start()
        self.root.after(100, self.process_queue)

    def _download_selected_chapters_thread(self, novel_id, cookies, download_folder, download_interval, selected_chapters):
        downloader = NovelpiaDownloader(novel_id, cookies, download_folder, download_interval, self.queue_log_action)
        
        downloaded_chapters = []
        total_chapters = len(selected_chapters)

        for i, chapter in enumerate(selected_chapters, 1):
            self.queue_log_action(f"Downloading chapter {chapter['number']}: {chapter['title']}")
            downloader.download_chapter(chapter)
            downloaded_chapters.append(chapter)
            progress = (i / total_chapters) * 100
            self.queue.put(("update_progress", progress))
            time.sleep(download_interval)

        self.queue_log_action("Compiling novel...")
        downloader.compile_novel(downloaded_chapters)
        self.queue_log_action("Novel download and compilation complete!")
        self.queue.put(("show_completion_message",))

    def process_queue(self):
        try:
            while True:
                message = self.queue.get_nowait()
                if message[0] == "log":
                    self.log_action(message[1])
                elif message[0] == "update_novel_info":
                    self.update_novel_info(message[1])
                elif message[0] == "update_chapter_list":
                    self.chapters = message[1]
                    self.update_chapter_list()
                elif message[0] == "update_progress":
                    self.progress_var.set(message[1])
                elif message[0] == "show_completion_message":
                    messagebox.showinfo("Download Complete", "Novel download and compilation complete!")
        except queue.Empty:
            pass
        finally:
            if self.thread is not None and self.thread.is_alive():
                self.root.after(100, self.process_queue)

    def queue_log_action(self, message):
        self.queue.put(("log", message))

    def log_action(self, message):
        if message.startswith("[ERROR]"):
            self.log_text.insert(tk.END, message + "\n", "error")
        else:
            self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

if __name__ == "__main__":
    root = tk.Tk()
    gui = NovelpiaDownloaderGUI(root)
    root.mainloop()
