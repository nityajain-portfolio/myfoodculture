import os
import mysql.connector
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, Response, jsonify
from werkzeug.utils import secure_filename
from functools import wraps

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.secret_key = 'supersecretkey'  # Change in production
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Load environment variables
from dotenv import load_dotenv

load_dotenv()

print("\n" + "=" * 60)
print("🚀 MyFoodCulture App Starting...")
print("=" * 60)
print(f"📁 Upload Folder: {app.config['UPLOAD_FOLDER']}")
print(f"🔑 Secret Key Set: {'Yes' if app.secret_key else 'No'}")
print("=" * 60 + "\n")


# Database connection
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )


# Helper function to get recipe images
def get_recipe_images(recipe_id, conn=None):
    """Get all images for a recipe"""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT * FROM recipe_images 
        WHERE recipe_id = %s 
        ORDER BY is_primary DESC, display_order ASC
    """, (recipe_id,))
    images = cursor.fetchall()
    cursor.close()

    if close_conn:
        conn.close()

    return images


# Helper function to add recipe images
def add_recipe_images(recipe_id, files):
    """Add multiple images for a recipe"""
    conn = get_db_connection()
    cursor = conn.cursor()

    saved_images = []
    for idx, file in enumerate(files):
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            # Add timestamp to filename to avoid conflicts
            import time
            timestamp = int(time.time())
            filename = f"{timestamp}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            # Insert into database
            is_primary = (idx == 0)  # First image is primary
            cursor.execute("""
                INSERT INTO recipe_images (recipe_id, image_path, is_primary, display_order)
                VALUES (%s, %s, %s, %s)
            """, (recipe_id, filepath, is_primary, idx))

            saved_images.append(filepath)
            print(f"📷 Image {idx + 1} saved: {filepath}")

    conn.commit()
    cursor.close()
    conn.close()

    return saved_images


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
    print("\n📄 Loading homepage...")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get latest recipes
    cursor.execute("SELECT * FROM recipes ORDER BY id DESC LIMIT 6")
    latest_recipes = cursor.fetchall()

    # Get recipes by category
    cursor.execute("SELECT * FROM recipes WHERE category = 'breakfast' ORDER BY id DESC")
    breakfast_recipes = cursor.fetchall()

    cursor.execute("SELECT * FROM recipes WHERE category = 'snacks' ORDER BY id DESC")
    snacks_recipes = cursor.fetchall()

    cursor.execute("SELECT * FROM recipes WHERE category = 'lunch_dinner' ORDER BY id DESC")
    lunch_dinner_recipes = cursor.fetchall()

    cursor.execute("SELECT * FROM recipes WHERE category = 'desserts' ORDER BY id DESC")
    desserts_recipes = cursor.fetchall()

    # Get quick recipes (15 minutes or less)
    cursor.execute(
        "SELECT * FROM recipes WHERE cooking_time_minutes <= 15 AND cooking_time_minutes IS NOT NULL ORDER BY cooking_time_minutes ASC")
    quick_recipes = cursor.fetchall()

    # Add images to recipes
    for recipe_list in [latest_recipes, breakfast_recipes, snacks_recipes, lunch_dinner_recipes, desserts_recipes,
                        quick_recipes]:
        for recipe in recipe_list:
            images = get_recipe_images(recipe['id'], conn)
            recipe['images'] = images
            recipe['primary_image'] = images[0] if images else None

    cursor.close()
    conn.close()

    print(f"✅ Loaded recipes for homepage\n")
    return render_template('index.html',
                           latest_recipes=latest_recipes,
                           breakfast_recipes=breakfast_recipes,
                           snacks_recipes=snacks_recipes,
                           lunch_dinner_recipes=lunch_dinner_recipes,
                           desserts_recipes=desserts_recipes,
                           quick_recipes=quick_recipes)


@app.route('/about')
def about():
    print("\n📖 Loading about page...")
    return render_template('about.html')


@app.route('/category/<string:cat>')
def category(cat):
    print(f"\n📂 Loading category: {cat}")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM recipes WHERE category = %s", (cat,))
    recipes = cursor.fetchall()

    # Add images
    for recipe in recipes:
        images = get_recipe_images(recipe['id'], conn)
        recipe['images'] = images
        recipe['primary_image'] = images[0] if images else None

    cursor.close()
    conn.close()
    print(f"✅ Found {len(recipes)} recipes in {cat}\n")
    return render_template('category.html', recipes=recipes, category=cat.capitalize().replace('_', '/'))


@app.route('/cuisine/<string:cuisine_type>')
def cuisine(cuisine_type):
    print(f"\n🌍 Loading cuisine: {cuisine_type}")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM recipes WHERE cuisine = %s", (cuisine_type,))
    recipes = cursor.fetchall()

    # Add images
    for recipe in recipes:
        images = get_recipe_images(recipe['id'], conn)
        recipe['images'] = images
        recipe['primary_image'] = images[0] if images else None

    cursor.close()
    conn.close()
    print(f"✅ Found {len(recipes)} recipes in {cuisine_type} cuisine\n")
    return render_template('category.html', recipes=recipes, category=cuisine_type.capitalize())


@app.route('/search', methods=['GET', 'POST'])
def search():
    query = request.form.get('q') if request.method == 'POST' else request.args.get('q', '')
    print(f"\n🔍 Searching for: {query}")
    if not query:
        return render_template('search.html', recipes=[], query='')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    # Search across all text fields in recipes table
    cursor.execute("""
        SELECT * FROM recipes 
        WHERE title LIKE %s 
        OR description LIKE %s 
        OR ingredients LIKE %s 
        OR directions LIKE %s
        OR category LIKE %s
        OR cuisine LIKE %s
    """, (f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%'))
    recipes = cursor.fetchall()

    # Add images
    for recipe in recipes:
        images = get_recipe_images(recipe['id'], conn)
        recipe['images'] = images
        recipe['primary_image'] = images[0] if images else None

    cursor.close()
    conn.close()
    print(f"✅ Found {len(recipes)} recipes\n")
    return render_template('search.html', recipes=recipes, query=query)


@app.route('/search-by-ingredients', methods=['GET', 'POST'])
def search_by_ingredients():
    """Search recipes by ingredients"""
    ingredients_query = request.form.get('ingredients') if request.method == 'POST' else request.args.get('ingredients',
                                                                                                          '')
    print(f"\n🥗 Searching by ingredients: {ingredients_query}")

    if not ingredients_query:
        return render_template('ingredient_search.html', recipes=[], ingredients_query='')

    # Split ingredients by comma and clean them
    ingredient_list = [ing.strip().lower() for ing in ingredients_query.split(',') if ing.strip()]

    if not ingredient_list:
        return render_template('ingredient_search.html', recipes=[], ingredients_query='')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Build query to find recipes containing ANY of the ingredients
    conditions = []
    params = []
    for ingredient in ingredient_list:
        conditions.append("LOWER(ingredients) LIKE %s")
        params.append(f'%{ingredient}%')

    query = f"SELECT * FROM recipes WHERE {' OR '.join(conditions)} ORDER BY id DESC"
    cursor.execute(query, params)
    recipes = cursor.fetchall()

    # Add images
    for recipe in recipes:
        images = get_recipe_images(recipe['id'], conn)
        recipe['images'] = images
        recipe['primary_image'] = images[0] if images else None

    cursor.close()
    conn.close()

    print(f"✅ Found {len(recipes)} recipes with those ingredients\n")
    return render_template('ingredient_search.html', recipes=recipes, ingredients_query=ingredients_query)


@app.route('/search-by-time/<string:time_range>')
def search_by_time(time_range):
    """Search recipes by cooking time"""
    print(f"\n⏱️ Searching by time: {time_range}")

    time_mapping = {
        '15min': 15,
        '30min': 30,
        '1hour': 60
    }

    max_minutes = time_mapping.get(time_range)
    if not max_minutes:
        flash('Invalid time range')
        return redirect(url_for('index'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM recipes WHERE cooking_time_minutes <= %s ORDER BY cooking_time_minutes ASC",
                   (max_minutes,))
    recipes = cursor.fetchall()

    # Add images
    for recipe in recipes:
        images = get_recipe_images(recipe['id'], conn)
        recipe['images'] = images
        recipe['primary_image'] = images[0] if images else None

    cursor.close()
    conn.close()

    time_label = {
        '15min': '15 minutes',
        '30min': '30 minutes',
        '1hour': '1 hour'
    }

    print(f"✅ Found {len(recipes)} recipes under {time_label[time_range]}\n")
    return render_template('category.html', recipes=recipes, category=f"Recipes in {time_label[time_range]} or less")


@app.route('/admin', methods=['GET', 'POST'])
@auth_required
def admin():
    if request.method == 'POST' and 'query' not in request.form:
        print("\n" + "=" * 60)
        print("📝 ATTEMPTING TO ADD NEW RECIPE")
        print("=" * 60)

        # Get form data
        title = request.form.get('title')
        category = request.form.get('category')
        cuisine = request.form.get('cuisine')
        description = request.form.get('description')
        ingredients = request.form.get('ingredients')
        directions = request.form.get('directions')
        cooking_time = request.form.get('cooking_time_minutes')
        added_by = request.form.get('added_by', 'nitya').strip() or 'nitya'  # Default to 'nitya'
        files = request.files.getlist('images')  # Multiple files

        # Debug output
        print(f"\n📋 Form Data Received:")
        print(f"   Title: {title}")
        print(f"   Category: {category}")
        print(f"   Cuisine: {cuisine}")
        print(f"   Cooking Time: {cooking_time}")
        print(f"   Added By: {added_by}")
        print(f"   Number of images: {len(files)}")

        # Validate required fields
        missing_fields = []
        if not title:
            missing_fields.append('title')
        if not category:
            missing_fields.append('category')
        # Cuisine is optional for breakfast and desserts
        if not cuisine and category not in ['breakfast', 'desserts']:
            missing_fields.append('cuisine')
        if not description:
            missing_fields.append('description')
        if not ingredients:
            missing_fields.append('ingredients')
        if not directions:
            missing_fields.append('directions')

        if missing_fields:
            error_msg = f'❌ Missing required fields: {", ".join(missing_fields)}'
            print(f"\n{error_msg}\n")
            flash(error_msg)
            return redirect(url_for('admin'))

        print("\n✅ All required fields present")

        # Handle cooking time
        cooking_time_value = int(cooking_time) if cooking_time and cooking_time.strip() else None

        # Insert recipe into database
        try:
            print("\n💾 Attempting to save to database...")
            conn = get_db_connection()
            cursor = conn.cursor()

            sql = "INSERT INTO recipes (title, category, cuisine, description, ingredients, directions, cooking_time_minutes, added_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            values = (title, category, cuisine, description, ingredients, directions, cooking_time_value, added_by)

            cursor.execute(sql, values)
            conn.commit()

            recipe_id = cursor.lastrowid
            print(f"✅ SUCCESS! Recipe saved with ID: {recipe_id}")

            cursor.close()
            conn.close()

            # Handle multiple images
            if files and any(f.filename for f in files):
                add_recipe_images(recipe_id, files)

            flash('Recipe added successfully!')
            print("=" * 60 + "\n")
            return redirect(url_for('admin'))

        except mysql.connector.Error as db_err:
            error_msg = f"❌ DATABASE ERROR: {str(db_err)}"
            print(f"\n{error_msg}")
            flash(f'Database error: {str(db_err)}')
            return redirect(url_for('admin'))

        except Exception as e:
            error_msg = f"❌ UNEXPECTED ERROR: {str(e)}"
            print(f"\n{error_msg}")
            flash(f'Error: {str(e)}')
            return redirect(url_for('admin'))

    # GET request - show all recipes
    print("\n📋 Loading admin page...")
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM recipes ORDER BY id DESC")
        recipes = cursor.fetchall()

        # Add images to recipes
        for recipe in recipes:
            images = get_recipe_images(recipe['id'], conn)
            recipe['images'] = images
            recipe['image_count'] = len(images)

        cursor.close()
        conn.close()
        print(f"✅ Loaded {len(recipes)} recipes for admin panel\n")
    except Exception as e:
        print(f"❌ ERROR loading recipes: {str(e)}\n")
        recipes = []
        flash(f'Error loading recipes: {str(e)}')

    return render_template('admin.html', recipes=recipes, edit_recipe=None)


@app.route('/admin/search', methods=['POST'])
@auth_required
def admin_search():
    query = request.form.get('query', '')
    print(f"\n🔍 Admin searching for: {query}")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM recipes WHERE title LIKE %s OR description LIKE %s ORDER BY id DESC",
        (f'%{query}%', f'%{query}%')
    )
    recipes = cursor.fetchall()

    # Add images
    for recipe in recipes:
        images = get_recipe_images(recipe['id'], conn)
        recipe['images'] = images
        recipe['image_count'] = len(images)

    cursor.close()
    conn.close()
    print(f"✅ Found {len(recipes)} recipes\n")
    return render_template('admin.html', recipes=recipes, query=query, edit_recipe=None)


@app.route('/recipe/<int:id>')
def recipe(id):
    print(f"\n📖 Loading recipe ID: {id}")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM recipes WHERE id = %s", (id,))
    recipe = cursor.fetchone()

    if recipe:
        # Get all images for this recipe
        recipe['images'] = get_recipe_images(id, conn)
        recipe['primary_image'] = recipe['images'][0] if recipe['images'] else None

    cursor.close()
    conn.close()

    if recipe:
        print(f"✅ Loaded recipe: {recipe['title']} with {len(recipe['images'])} images\n")
        return render_template('recipe.html', recipe=recipe)
    else:
        print(f"❌ Recipe {id} not found\n")
        from flask import abort
        abort(404)


@app.route('/admin/edit/<int:id>', methods=['GET', 'POST'])
@auth_required
def edit_recipe(id):
    if request.method == 'POST':
        print(f"\n✏️  Editing recipe ID: {id}")

        title = request.form.get('title')
        category = request.form.get('category')
        cuisine = request.form.get('cuisine')
        description = request.form.get('description')
        ingredients = request.form.get('ingredients')
        directions = request.form.get('directions')
        cooking_time = request.form.get('cooking_time_minutes')
        added_by = request.form.get('added_by', 'nitya').strip() or 'nitya'  # Default to 'nitya'
        files = request.files.getlist('images')

        # Validate required fields
        missing_fields = []
        if not title:
            missing_fields.append('title')
        if not category:
            missing_fields.append('category')
        if not cuisine and category not in ['breakfast', 'desserts']:
            missing_fields.append('cuisine')
        if not description:
            missing_fields.append('description')
        if not ingredients:
            missing_fields.append('ingredients')
        if not directions:
            missing_fields.append('directions')

        if missing_fields:
            flash(f'Missing required fields: {", ".join(missing_fields)}')
            return redirect(url_for('edit_recipe', id=id))

        cooking_time_value = int(cooking_time) if cooking_time and cooking_time.strip() else None

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Update recipe
            cursor.execute("""
                UPDATE recipes 
                SET title=%s, category=%s, cuisine=%s, description=%s, 
                    ingredients=%s, directions=%s, cooking_time_minutes=%s, added_by=%s 
                WHERE id=%s
            """, (title, category, cuisine, description, ingredients, directions, cooking_time_value, added_by, id))

            conn.commit()
            cursor.close()
            conn.close()

            # Handle new images if uploaded
            if files and any(f.filename for f in files):
                add_recipe_images(id, files)

            print(f"✅ Recipe {id} updated successfully\n")
            flash('Recipe updated successfully!')
            return redirect(url_for('admin'))

        except Exception as e:
            print(f"❌ Error updating recipe: {str(e)}\n")
            flash(f'Error updating recipe: {str(e)}')
            return redirect(url_for('edit_recipe', id=id))

    # GET request
    print(f"\n🔍 Loading recipe {id} for editing...")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM recipes WHERE id = %s", (id,))
    recipe = cursor.fetchone()

    if recipe:
        recipe['images'] = get_recipe_images(id, conn)

    cursor.execute("SELECT * FROM recipes ORDER BY id DESC")
    recipes = cursor.fetchall()

    for r in recipes:
        r['images'] = get_recipe_images(r['id'], conn)
        r['image_count'] = len(r['images'])

    cursor.close()
    conn.close()

    if recipe:
        return render_template('admin.html', edit_recipe=recipe, recipes=recipes)
    else:
        flash('Recipe not found!')
        return redirect(url_for('admin'))


@app.route('/admin/delete-image/<int:image_id>', methods=['POST'])
@auth_required
def delete_image(image_id):
    """Delete a single image from a recipe"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Get image info
        cursor.execute("SELECT * FROM recipe_images WHERE id = %s", (image_id,))
        image = cursor.fetchone()

        if image:
            # Delete file if exists
            if os.path.exists(image['image_path']):
                os.remove(image['image_path'])

            # Delete from database
            cursor.execute("DELETE FROM recipe_images WHERE id = %s", (image_id,))
            conn.commit()

            flash('Image deleted successfully!')
        else:
            flash('Image not found!')

        cursor.close()
        conn.close()

    except Exception as e:
        flash(f'Error deleting image: {str(e)}')

    return redirect(request.referrer or url_for('admin'))


@app.route('/admin/delete/<int:id>')
@auth_required
def delete_recipe(id):
    print(f"\n🗑️  Deleting recipe ID: {id}")

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Get and delete all images
        images = get_recipe_images(id, conn)
        for image in images:
            if os.path.exists(image['image_path']):
                os.remove(image['image_path'])

        # Delete recipe (cascade will delete images from DB)
        cursor.execute("DELETE FROM recipes WHERE id = %s", (id,))
        conn.commit()
        cursor.close()
        conn.close()

        print(f"✅ Recipe {id} deleted successfully\n")
        flash('Recipe deleted successfully!')

    except Exception as e:
        print(f"❌ Error deleting recipe: {str(e)}\n")
        flash(f'Error deleting recipe: {str(e)}')

    return redirect(url_for('admin'))


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    print("✅ Upload folder created/verified\n")
    print("🌐 Starting Flask server on http://127.0.0.1:5000")
    print("Press Ctrl+C to stop the server\n")
    app.run(debug=True)