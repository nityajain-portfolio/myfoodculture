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


# Helper function to enrich recipes with images
def enrich_recipes_with_images(recipes, conn=None):
    """Add images and image_path to recipes for template compatibility"""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    for recipe in recipes:
        images = get_recipe_images(recipe['id'], conn)
        recipe['images'] = images
        recipe['primary_image'] = images[0] if images else None
        # Add image_path for backward compatibility with templates
        recipe['image_path'] = images[0]['image_path'] if images else None

    if close_conn:
        conn.close()

    return recipes


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

    # Add images to all recipe lists using the helper function
    for recipe_list in [latest_recipes, breakfast_recipes, snacks_recipes, lunch_dinner_recipes, desserts_recipes,
                        quick_recipes]:
        enrich_recipes_with_images(recipe_list, conn)

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

    # Add images using helper function
    enrich_recipes_with_images(recipes, conn)

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

    # Add images using helper function
    enrich_recipes_with_images(recipes, conn)

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

    # Add images using helper function
    enrich_recipes_with_images(recipes, conn)

    cursor.close()
    conn.close()
    print(f"✅ Found {len(recipes)} recipes\n")
    return render_template('search.html', recipes=recipes, query=query)


@app.route('/search-by-time/<time_range>')
def search_by_time(time_range):
    print(f"\n⏰ Searching recipes by time: {time_range}")

    # Map time_range to minutes
    time_map = {
        '15min': 15,
        '30min': 30,
        '1hour': 60
    }

    max_time = time_map.get(time_range, 30)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM recipes WHERE cooking_time_minutes <= %s AND cooking_time_minutes IS NOT NULL ORDER BY cooking_time_minutes ASC",
        (max_time,)
    )
    recipes = cursor.fetchall()

    # Add images using helper function
    enrich_recipes_with_images(recipes, conn)

    cursor.close()
    conn.close()

    print(f"✅ Found {len(recipes)} recipes under {max_time} minutes\n")
    return render_template('search_time.html', recipes=recipes, time_range=time_range, max_time=max_time)


@app.route('/search-by-ingredients', methods=['GET', 'POST'])
def search_by_ingredients():
    if request.method == 'POST':
        ingredients_input = request.form.get('ingredients', '')
        print(f"\n🥕 Searching by ingredients: {ingredients_input}")

        # Split ingredients by comma and clean them
        ingredients = [ing.strip().lower() for ing in ingredients_input.split(',') if ing.strip()]

        if not ingredients:
            return render_template('search_ingredients.html', recipes=[], query='')

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Build dynamic query - recipe must contain ALL ingredients
        query = "SELECT * FROM recipes WHERE "
        conditions = []
        params = []

        for ingredient in ingredients:
            conditions.append("LOWER(ingredients) LIKE %s")
            params.append(f'%{ingredient}%')

        query += " AND ".join(conditions)

        cursor.execute(query, params)
        recipes = cursor.fetchall()

        # Add images using helper function
        enrich_recipes_with_images(recipes, conn)

        cursor.close()
        conn.close()

        print(f"✅ Found {len(recipes)} recipes with ingredients: {', '.join(ingredients)}\n")
        return render_template('search_ingredients.html', recipes=recipes, query=ingredients_input)

    # GET request
    return render_template('search_ingredients.html', recipes=[], query='')


@app.route('/admin/add', methods=['GET', 'POST'])
@auth_required
def add_recipe():
    if request.method == 'POST':
        print("\n➕ Adding new recipe...")

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
            return redirect(url_for('add_recipe'))

        cooking_time_value = int(cooking_time) if cooking_time and cooking_time.strip() else None

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Insert recipe
            cursor.execute("""
                INSERT INTO recipes (title, category, cuisine, description, ingredients, directions, cooking_time_minutes, added_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (title, category, cuisine, description, ingredients, directions, cooking_time_value, added_by))

            recipe_id = cursor.lastrowid
            conn.commit()
            cursor.close()
            conn.close()

            # Handle image uploads
            if files and any(f.filename for f in files):
                add_recipe_images(recipe_id, files)

            print(f"✅ Recipe '{title}' added successfully with ID {recipe_id}\n")
            flash('Recipe added successfully!')
            return redirect(url_for('admin'))

        except Exception as e:
            print(f"❌ Error adding recipe: {str(e)}\n")
            flash(f'Error adding recipe: {str(e)}')
            return redirect(url_for('add_recipe'))

    return render_template('add_recipe.html')


@app.route('/admin')
@auth_required
def admin():
    print("\n🔐 Loading admin panel...")
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
        # Add image_path for backward compatibility
        recipe['image_path'] = recipe['images'][0]['image_path'] if recipe['images'] else None

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