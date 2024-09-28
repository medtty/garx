import sys
import os
import configparser
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QListWidget,
    QTextEdit,
    QMessageBox,
    QComboBox,
    QDialog,
    QScrollArea,
    QListWidgetItem,
    QMainWindow,
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QUrl
from PyQt5.QtGui import QIcon
from PyQt5.QtWebEngineWidgets import QWebEngineView
from arxiv_utils import fetch_arxiv_papers, summarize_paper, translate_with_groq, talk_to_paper_with_groq, download_paper
import logging

# Apply dark mode and blue accent styling
style = """
QWidget {
    background-color: #2E2E2E; /* Dark background */
    color: #FFFFFF; /* Light text */
}
QLineEdit, QTextEdit, QComboBox {
    background-color: #3E3E3E; /* Dark input fields */
    color: #FFFFFF;
    border: 1px solid #1E1E1E;
    border-radius: 5px;
    padding: 5px;
}
QPushButton {
    background-color: #007BFF; /* Blue button */
    color: white;
    border-radius: 5px;
    padding: 6px;
}
QPushButton:hover {
    background-color: #0056b3; /* Darker blue on hover */
}
QListWidget {
    background-color: #3E3E3E;
    border: 1px solid #1E1E1E;
}
QScrollArea {
    border: none;
}
QLabel {
    font-size: 12pt;
}
"""

class ProcessingThread(QThread):
    finished = pyqtSignal(str, str)

    def __init__(self, paper):
        QThread.__init__(self)
        self.paper = paper

    def run(self):
        summary = summarize_paper(self.paper["summary"])
        self.finished.emit(summary, self.paper["summary"])

class PDFViewer(QMainWindow):
    def __init__(self, pdf_path):
        super().__init__()
        self.setWindowTitle("PDF Viewer")
        self.setGeometry(100, 100, 800, 600)

        self.web_view = QWebEngineView()
        self.setCentralWidget(self.web_view)

        pdf_url = QUrl.fromLocalFile(pdf_path)
        self.web_view.setUrl(pdf_url)

class ChatThread(QThread):
    finished = pyqtSignal(str)

    def __init__(self, paper_text, question, use_groq=False):
        super().__init__()
        self.paper_text = paper_text
        self.question = question
        self.use_groq = use_groq

    def run(self):
        if self.use_groq:
            answer = talk_to_paper_with_groq(self.paper_text, self.question)
        else:
            answer = "Error: Unsupported chat method"
        
        self.finished.emit(answer)

class TranslationWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Translation")
        self.setGeometry(350, 350, 600, 400)
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout()

        hbox = QHBoxLayout()
        self.lang_combo = QComboBox(self)
        self.lang_combo.addItems(["English", "Arabic", "Chinese"])
        hbox.addWidget(QLabel("Translate to:"))
        hbox.addWidget(self.lang_combo)
        layout.addLayout(hbox)

        self.translate_btn = QPushButton("Translate", self)
        self.translate_btn.setCursor(Qt.PointingHandCursor)
        self.translate_btn.clicked.connect(self.translate_text)
        layout.addWidget(self.translate_btn)

        self.translation_area = QTextEdit(self)
        self.translation_area.setReadOnly(True)
        layout.addWidget(self.translation_area)

        self.setLayout(layout)

    def set_text(self, text):
        self.original_text = text

    def translate_text(self):
        target_language = self.lang_combo.currentText()
        self.translation_area.setText("Translating... Please wait.")
        translated_text = translate_with_groq(self.original_text, target_language)
        self.translation_area.setText(translated_text)

class ChatBubble(QWidget):
    def __init__(self, text, is_user=True, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout()
        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setStyleSheet(
            "background-color: #007BFF;" if is_user else "#E0E0E0;"
            "border-radius: 10px; padding: 10px; color: black;"
        )
        if is_user:
            layout.addStretch()
        layout.addWidget(bubble)
        if not is_user:
            layout.addStretch()
        self.setLayout(layout)

class ArxivApp(QWidget):
    def __init__(self):
        super().__init__()
        self.config = configparser.ConfigParser()
        self.config.read('key.ini')
        self.translation_window = TranslationWindow(self)
        self.pdf_viewer = None  # Initialize pdf_viewer as None
        self.initUI()

class ArxivApp(QWidget):
    def __init__(self):
        super().__init__()
        self.config = configparser.ConfigParser()
        self.config.read('key.ini')
        self.translation_window = TranslationWindow(self)
        self.pdf_viewer = None  # Initialize pdf_viewer as None
        self.initUI()

    def initUI(self):
        self.setWindowTitle("GARX")
        self.setGeometry(300, 300, 800, 600)
        self.setStyleSheet(style)  # Apply the dark mode style

        layout = QVBoxLayout()

        # Search Bar Layout
        search_layout = QHBoxLayout()
        self.query_input = QLineEdit(self)
        self.query_input.setPlaceholderText("Enter arXiv search query")
        search_layout.addWidget(self.query_input)

        # Search Button with icon
        self.search_btn = QPushButton("Search", self)
        self.search_btn.setCursor(Qt.PointingHandCursor)
        self.search_btn.setIcon(QIcon("icons/search_icon.png"))  # Add your icon path
        self.search_btn.clicked.connect(self.search_papers)
        search_layout.addWidget(self.search_btn)

        # Translate Button
        self.translate_btn = QPushButton("Translate", self)
        self.translate_btn.setCursor(Qt.PointingHandCursor)
        self.translate_btn.clicked.connect(self.open_translation_window)
        self.translate_btn.setEnabled(False)
        search_layout.addWidget(self.translate_btn)

        layout.addLayout(search_layout)

        # Three Columns Layout
        main_layout = QHBoxLayout()

        # Search Results Column
        self.papers_list = QListWidget(self)
        self.papers_list.setCursor(Qt.PointingHandCursor)
        self.papers_list.setSpacing(5)
        main_layout.addWidget(self.papers_list)

        # Summary Column
        summary_layout = QVBoxLayout()
        self.output_area = QTextEdit(self)
        self.output_area.setReadOnly(True)
        summary_layout.addWidget(self.output_area)

        # Summarize Button
        self.summarize_btn = QPushButton("Summarize", self)
        self.summarize_btn.setCursor(Qt.PointingHandCursor)
        self.summarize_btn.clicked.connect(self.process_paper)
        self.summarize_btn.setEnabled(False)
        summary_layout.addWidget(self.summarize_btn)

        # Add Download and Preview buttons
        button_layout = QHBoxLayout()
        self.download_btn = QPushButton("Download", self)
        self.download_btn.setCursor(Qt.PointingHandCursor)
        self.download_btn.clicked.connect(self.download_selected_paper)
        self.download_btn.setEnabled(False)
        button_layout.addWidget(self.download_btn)

        self.preview_btn = QPushButton("Preview", self)
        self.preview_btn.setCursor(Qt.PointingHandCursor)
        self.preview_btn.clicked.connect(self.preview_selected_paper)
        self.preview_btn.setEnabled(False)
        button_layout.addWidget(self.preview_btn)

        summary_layout.addLayout(button_layout)

        main_layout.addLayout(summary_layout)

        # Chat Section Column
        chat_layout = QVBoxLayout()
        chat_label = QLabel("Chat with the Paper")
        chat_layout.addWidget(chat_label)

        self.chat_area = QScrollArea()
        self.chat_widget = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_widget)
        self.chat_area.setWidget(self.chat_widget)
        self.chat_area.setWidgetResizable(True)
        chat_layout.addWidget(self.chat_area)

        input_layout = QHBoxLayout()
        self.question_input = QLineEdit(self)
        self.question_input.setPlaceholderText("Ask a question about the paper")
        input_layout.addWidget(self.question_input)
        self.ask_btn = QPushButton("Ask", self)
        self.ask_btn.setCursor(Qt.PointingHandCursor)
        self.ask_btn.setIcon(QIcon("icons/chat_icon.png"))  # Add your icon path
        self.ask_btn.clicked.connect(self.start_chat_thread)
        input_layout.addWidget(self.ask_btn)
        chat_layout.addLayout(input_layout)

        main_layout.addLayout(chat_layout)

        layout.addLayout(main_layout)

        self.setLayout(layout)

    def search_papers(self):
        query = self.query_input.text()
        if not query:
            QMessageBox.warning(self, "Error", "Please enter a search query.")
            return

        max_results = int(self.config["arXiv"]["MAX_RESULTS"])
        papers = fetch_arxiv_papers(query, max_results=max_results)
        if papers:
            self.papers_list.clear()
            for paper in papers:
                item = QListWidgetItem(f"{paper['title']}\nID: {paper['id']} | Date: {paper['published_date']} | Authors: {', '.join(paper['authors'])}")
                item.setData(Qt.UserRole, paper)
                self.papers_list.addItem(item)
            self.papers = papers
            self.summarize_btn.setEnabled(True)
            self.download_btn.setEnabled(True)
            self.preview_btn.setEnabled(True)
        else:
            QMessageBox.warning(self, "Error", "Failed to fetch papers. Try again.")

    def process_paper(self):
        selected_item = self.papers_list.currentItem()
        if selected_item:
            selected_paper = selected_item.data(Qt.UserRole)
            self.output_area.setText("Processing... Please wait.")

            self.thread = ProcessingThread(selected_paper)
            self.thread.finished.connect(self.on_processing_finished)
            self.thread.start()
        else:
            QMessageBox.warning(self, "Error", "Please select a paper from the list.")

    def download_selected_paper(self):
        selected_item = self.papers_list.currentItem()
        if selected_item:
            paper = selected_item.data(Qt.UserRole)
            filename = download_paper(paper['pdf_url'], paper['id'])
            if filename:
                QMessageBox.information(self, "Success", f"Paper downloaded as {filename}")
            else:
                QMessageBox.warning(self, "Error", "Failed to download the paper.")
        else:
            QMessageBox.warning(self, "Error", "Please select a paper from the list.")

    def preview_selected_paper(self):
        selected_item = self.papers_list.currentItem()
        if selected_item:
            paper = selected_item.data(Qt.UserRole)
            filename = f"{paper['id']}.pdf"
            if not os.path.exists(filename):
                filename = download_paper(paper['pdf_url'], paper['id'])
            if filename:
                if self.pdf_viewer is None:
                    self.pdf_viewer = PDFViewer(os.path.abspath(filename))
                else:
                    self.pdf_viewer.web_view.setUrl(QUrl.fromLocalFile(os.path.abspath(filename)))
                self.pdf_viewer.show()
            else:
                QMessageBox.warning(self, "Error", "Failed to open the paper.")
        else:
            QMessageBox.warning(self, "Error", "Please select a paper from the list.")

    def on_processing_finished(self, summary, full_text):
        self.output_area.setText(f"Summary:\n{summary}")
        self.current_paper_text = full_text
        self.translate_btn.setEnabled(True)  # Enable the translate button

    def open_translation_window(self):
        if hasattr(self, 'current_paper_text'):
            self.translation_window.set_text(self.output_area.toPlainText())  # Set the text to be translated
            self.translation_window.show()  # Show the translation window
        else:
            QMessageBox.warning(self, "Error", "Please process a paper first.")

    def start_chat_thread(self):
        if hasattr(self, 'current_paper_text'):
            question = self.question_input.text()
            if question:
                self.add_chat_bubble(question, True)
                self.question_input.clear()
                QApplication.processEvents()

                # Start the chat thread with Groq
                self.chat_thread = ChatThread(self.current_paper_text, question, use_groq=True)
                self.chat_thread.finished.connect(self.on_chat_finished)
                self.chat_thread.start()

                # Disable the ask button and show a loading message
                self.ask_btn.setEnabled(False)
                self.ask_btn.setCursor(Qt.PointingHandCursor)
                self.add_chat_bubble("Thinking...", False)
            else:
                QMessageBox.warning(self, "Error", "Please enter a question.")
        else:
            QMessageBox.warning(self, "Error", "Please process a paper first.")

    def on_chat_finished(self, answer):
        self.chat_layout.itemAt(self.chat_layout.count() - 1).widget().setParent(None)
        self.add_chat_bubble(answer, False)
        self.ask_btn.setEnabled(True)
        self.ask_btn.setCursor(Qt.PointingHandCursor)

    def add_chat_bubble(self, text, is_user):
        bubble = ChatBubble(text, is_user)
        self.chat_layout.addWidget(bubble)
        self.chat_area.verticalScrollBar().setValue(self.chat_area.verticalScrollBar().maximum())

# Initialize and run the PyQt5 application
if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = ArxivApp()
    ex.show()
    sys.exit(app.exec_())
