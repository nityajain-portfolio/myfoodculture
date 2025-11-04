import os
import mysql.connector
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, Response
from werkzeug.utils import secure_filename
from functools import wraps

app = Flask(__name__)
app.secret_key = 'supersecretkey'  # Change in production
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}

# Load environment variables
from dotenv import load_dotenv

load_dotenv()


# Database connection
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )


# Basic auth decorator
def auth_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.username != os.getenv('ADMIN_USER') or auth.password != os.getenv('ADMIN_PASS'):
            return Response(
                'Unauthorized', 401,
                {'WWW-Authenticate': 'Basic realm="Admin Login"'}
            )
        return f(*args, **kwargs)

    return decorated


# Check allowed file
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


@app.route('/')
def index():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM recipes ORDER BY id DESC LIMIT 6")  # Latest 6 recipes
    recipes = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('index.html', recipes=recipes)


@app.route('/category/<string:cat>')
def category(cat):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM recipes WHERE category = %s", (cat,))
    recipes = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('category.html', recipes=recipes, category=cat.capitalize().replace('_', '/'))


@app.route('/search', methods=['GET', 'POST'])
def search():
    if request.method == 'POST':
        query = request.form['query']
        if not query:
            flash('Please enter a search term.')
            return redirect(url_for('index'))

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM recipes WHERE title LIKE %s OR description LIKE %s",
            (f'%{query}%', f'%{query}%')
        )
        recipes = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template('search.html', recipes=recipes, query=query)

    return redirect(url_for('index'))


@app.route('/admin', methods=['GET', 'POST'])
@auth_required
def admin():
    if request.method == 'POST' and 'query' not in request.form:
        title = request.form['title']
        category = request.form['category']
        description = request.form['description']
        file = request.files.get('image')

        if not title or not category or not description:
            flash('All fields are required!')
            return redirect(url_for('admin'))

        image_path = None
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO recipes (title, category, description, image_path) VALUES (%s, %s, %s, %s)",
            (title, category, description, image_path)
        )
        conn.commit()
        cursor.close()
        conn.close()
        flash('Recipe added successfully!')
        return redirect(url_for('admin'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM recipes")
    recipes = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('admin.html', recipes=recipes)


@app.route('/admin/search', methods=['POST'])
@auth_required
def admin_search():
    query = request.form['query']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM recipes WHERE title LIKE %s OR description LIKE %s",
        (f'%{query}%', f'%{query}%')
    )
    recipes = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('admin.html', recipes=recipes, query=query)


@app.route('/admin/edit/<int:id>', methods=['GET', 'POST'])
@auth_required
def edit_recipe(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        title = request.form['title']
        category = request.form['category']
        description = request.form['description']
        file = request.files.get('image')

        if not title or not category or not description:
            flash('All fields are required!')
            cursor.close()
            conn.close()
            return redirect(url_for('edit_recipe', id=id))

        cursor.execute("SELECT image_path FROM recipes WHERE id = %s", (id,))
        old_recipe = cursor.fetchone()
        image_path = old_recipe['image_path']

        if file and allowed_file(file.filename):
            if image_path and os.path.exists(image_path):
                os.remove(image_path)
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        cursor.execute(
            "UPDATE recipes SET title = %s, category = %s, description = %s, image_path = %s WHERE id = %s",
            (title, category, description, image_path, id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        flash('Recipe updated successfully!')
        return redirect(url_for('admin'))

    cursor.execute("SELECT * FROM recipes WHERE id = %s", (id,))
    recipe = cursor.fetchone()
    cursor.close()
    conn.close()
    if not recipe:
        flash('Recipe not found!')
        return redirect(url_for('admin'))
    return render_template('admin.html', recipes=[], edit_recipe=recipe)


@app.route('/admin/delete/<int:id>')
@auth_required
def delete_recipe(id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT image_path FROM recipes WHERE id = %s", (id,))
    recipe = cursor.fetchone()
    if recipe and recipe[0] and os.path.exists(recipe[0]):
        os.remove(recipe[0])

    cursor.execute("DELETE FROM recipes WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    flash('Recipe deleted successfully!')
    return redirect(url_for('admin'))


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.run(debug=True)