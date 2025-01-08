# My Flask App

This is a simple Flask application that demonstrates the use of Bootstrap for styling and layout.

## Project Structure

```
my-flask-app
├── app
│   ├── static
│   │   ├── css
│   │   │   └── bootstrap.min.css
│   │   ├── js
│   │   │   └── bootstrap.min.js
│   ├── templates
│   │   └── index.html
│   ├── __init__.py
│   └── routes.py
├── venv
├── requirements.txt
├── config.py
└── README.md
```

## Setup Instructions

1. Clone the repository:
   ```
   git clone <repository-url>
   cd my-flask-app
   ```

2. Create a virtual environment:
   ```
   python -m venv venv
   ```

3. Activate the virtual environment:
   - On Windows:
     ```
     venv\Scripts\activate
     ```
   - On macOS/Linux:
     ```
     source venv/bin/activate
     ```

4. Install the required packages:
   ```
   pip install -r requirements.txt
   ```

5. Run the application:
   ```
   flask run
   ```

## Usage

Open your web browser and go to `http://127.0.0.1:5000` to view the application. 

## License

This project is licensed under the MIT License.