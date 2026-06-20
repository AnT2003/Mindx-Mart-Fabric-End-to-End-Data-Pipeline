# E-Commerce Sentiment Analysis Pipeline

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100.0-00a393)
![TensorFlow](https://img.shields.io/badge/TensorFlow-2.x-FF6F00)
![XGBoost](https://img.shields.io/badge/XGBoost-1.7-F37626)
![Apache Spark](https://img.shields.io/badge/PySpark-Data%20Engineering-E25A1C)

## 📌 Project Overview
This project provides a complete, end-to-end Data Engineering and Machine Learning pipeline for Sentiment Analysis on Vietnamese E-commerce product reviews. 

The pipeline automates the data ingestion process from external APIs, processes large-scale textual data using Spark/Pandas, balances classes using SMOTE, and trains highly accurate sentiment classification models (XGBoost & BiLSTM). Finally, it serves the models through a high-performance REST API built with FastAPI, complete with a modern Glassmorphism Web UI.

## ✨ Key Features
- **Data Ingestion (Crawler):** Automated data scraping mechanism targeting product listings and customer reviews with built-in fault tolerance and request throttling.
- **Data Engineering:** Scalable text processing pipeline. Includes Vietnamese tokenization (`pyvi`), noise removal, and data standardization outputting to optimized `.parquet` format.
- **Machine Learning (XGBoost):** TF-IDF vectorization paired with gradient boosting, optimized via hyperparameter tuning to achieve high precision and fast inference.
- **Deep Learning (BiLSTM):** Custom recurrent neural network architecture utilizing Bidirectional LSTM layers, Dropout regularization, and Early Stopping for capturing deep sequential context.
- **RESTful API & Web UI:** Fast, async API serving the models, documented via Swagger UI, accompanied by a dynamic, responsive web interface.

## 🛠️ Technology Stack
- **Data Engineering:** `pandas`, `pyspark`, `requests`, `pyarrow`
- **Machine Learning:** `scikit-learn`, `xgboost`, `imblearn` (SMOTE)
- **Deep Learning:** `tensorflow`, `keras`
- **NLP Processing:** `pyvi`, `nltk`
- **Backend & Serving:** `fastapi`, `uvicorn`, `jinja2`
- **Frontend:** `HTML5`, `CSS3` (Glassmorphism design), `Vanilla JS`

## 📂 Project Structure
```text
Sentiment-Analysis-Project/
├── api/
│   ├── main.py                # FastAPI application setup and routing
│   └── schemas.py             # Pydantic schemas for request/response validation
├── data/
│   ├── raw/                   # Raw crawled CSV files
│   └── processed/             # Cleaned and tokenized Parquet files
├── models/                    # Serialized models (.pkl, .h5) and tokenizers
├── notebooks/                 # Exploratory Data Analysis & Prototyping
├── src/
│   ├── data_engineering/
│   │   ├── crawler.py         # E-commerce review crawler script
│   │   ├── pandas_processing.py # Local data processing pipeline
│   │   └── spark_processing.py  # Distributed data processing pipeline (PySpark)
│   ├── models/
│   │   ├── train_bilstm.py    # Deep Learning training pipeline
│   │   └── train_xgboost.py   # Machine Learning training pipeline
│   └── utils/
│       └── text_processing.py # NLP utilities (cleaning, tokenization)
├── templates/
│   └── index.html             # Modern Web UI template
├── requirements.txt           # Project dependencies
└── README.md                  # Project documentation
```

## 🚀 Installation & Setup

### 1. Prerequisites
- Python 3.8 or higher.
- Java 8 (Required for Apache Spark/PySpark).
- Virtual Environment tool (`venv` or `conda`).

### 2. Environment Setup
Clone the repository and install dependencies:
```bash
git clone <repository_url>
cd Sentiment-Analysis-Project

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install required packages
pip install -r requirements.txt
```

## ⚙️ Usage Guide

### Step 1: Data Ingestion
Run the crawler to fetch the latest product reviews.
```bash
python src/data_engineering/crawler.py --max_product_pages 5 --max_comment_pages 10
```

### Step 2: Data Processing
Process the raw `.csv` files into tokenized `.parquet` format for optimized training.
```bash
# Using standard Pandas pipeline
python src/data_engineering/pandas_processing.py

# OR Using PySpark for large datasets
python src/data_engineering/spark_processing.py
```

### Step 3: Model Training
Train the classification models. The scripts handle train/test splitting, SMOTE balancing, training, evaluation, and serialization.
```bash
# Train XGBoost Model
python src/models/train_xgboost.py

# Train Deep Learning BiLSTM Model
python src/models/train_bilstm.py
```

### Step 4: Start the API Server
Launch the FastAPI application to serve predictions.
```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

## 🌐 API Reference

Once the server is running, the interactive Swagger documentation is automatically available at:
`http://localhost:8000/docs`

### Endpoints
- `GET /` : Renders the web interface.
- `POST /api/predict/xgboost` : Predicts sentiment using the XGBoost model.
- `POST /api/predict/bilstm` : Predicts sentiment using the BiLSTM model.

**Payload Example:**
```json
{
  "comment": "Sản phẩm chất lượng rất tốt, giao hàng nhanh chóng!"
}
```

**Response Example:**
```json
{
  "sentiment": "positive",
  "confidence": 0.985
}
```

## 📄 License
This project is licensed under the MIT License. Feel free to use, modify, and distribute as per the license terms.
