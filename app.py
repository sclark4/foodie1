from flask import (Flask, render_template, make_response, url_for, request,
                   redirect, flash, session, send_from_directory, jsonify)
from werkzeug.utils import secure_filename
app = Flask(__name__)

import cs304dbi as dbi
import menuUpdates as menuUp #module to update foodie database from the menu page
import random   
import sys
import pymysql
import feed_queries
import query
import bcrypt
from flask_cas import CAS
import entry

from datetime import date,datetime

CAS(app)

app.config['CAS_SERVER'] = 'https://login.wellesley.edu:443'
app.config['CAS_LOGIN_ROUTE'] = '/module.php/casserver/cas.php/login'
app.config['CAS_LOGOUT_ROUTE'] = '/module.php/casserver/cas.php/logout'
app.config['CAS_VALIDATE_ROUTE'] = '/module.php/casserver/serviceValidate.php'
app.config['CAS_AFTER_LOGIN'] = 'profile_error' 
# the following doesn't work :-(
app.config['CAS_AFTER_LOGOUT'] = 'home'

app.secret_key = 'your secret here'
# replace that with a random key
app.secret_key = ''.join([ random.choice(('ABCDEFGHIJKLMNOPQRSTUVXYZ' +
                                          'abcdefghijklmnopqrstuvxyz' +
                                          '0123456789'))
                           for i in range(20) ])

# This gets us better error messages for certain common request errors
app.config['TRAP_BAD_REQUEST_ERRORS'] = True
# file upload content 
app.config['UPLOADS'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 1*1024*1024 # 1 MB

def today():
    """Returns a tuple with the string for the current day and time (SQL format)
    and a string for the day/time for display purposes. This is used to primarily to query the database according
    to the lastServed date for a given food item.
    """
    now = date.today()
    return now.strftime("%Y-%m-%d"), now.strftime("%A, %B %d")

@app.route('/pic/<int:fid>') 
#route to image for food photos, can later be generalized and applied to other photos too
def pic(fid):
    conn = dbi.connect()
    curs = dbi.cursor(conn)
    sql = '''select filename from foodPics where fid = %s'''
    curs.execute(sql, [fid])
    try:
        filename = curs.fetchone()[0]
        return send_from_directory(app.config['UPLOADS'],filename)
    except Exception as err: #in the case when there is not yet a photo uploaded
        return None

@app.route('/')
def home():
    # the base template needs only one filler
    return render_template('home.html',title='foodie.')

@app.route('/mainmenu/')
def mainmenu():
    '''Page with menu and form without any filters'''
    conn = dbi.connect()
    menu = menuUp.lookupMenuList(conn, today()[0])
    return render_template('menu.html',date=today()[1], menu = menu, title ="Menu")

@app.route('/menu/', methods=["GET"])
def menu():
    '''route for menu that is filtered in some way, either through a specific tag or a search'''
    conn = dbi.connect()
    if request.method == 'GET':
        # mealtype = ""
        dh = request.args.get('dh-filter', "")
        mealtype = request.args.get("type-filter", "")
        preference = request.args.getlist("preference")
        now = today()[0]
        if preference:
            preference = ",".join(preference)
        else:
            preference = ""
        if dh:
            dhName = menuUp.lookupDH(conn, dh)[0]
            waitTime = menuUp.getWaittime(conn, int(dh))[0]
        else:
            dhName = ""
            waitTime = ""
        # IMPLEMENT SEARCH BY LABEL label = ""
        search = request.args.get("query", "")
        # the variable date = today()[] generates the current date to display on the menu page
        if dh == '3' or dh == '4':
            flash("So sorry to be the bearer of bad news, but {} is closed today.".format(dhName))
        if dh or mealtype or preference: #if given a dining hall request and mealtype
            menu = menuUp.filterMenuList(conn, dh, mealtype,preference,now)
        elif search:
            menu = menuUp.searchMenu(conn, search)
            print(menu)
            if len(menu)==1:
                # if there's only one matching result, redirect directly to the food page 
                fid=menu[0]['fid']
                return redirect(url_for('food',fid=int(fid)))
            elif len(menu)==0:
                flash('''The name you entered does not match any dish in the database
                    Would you like to add a new food entry? ''')
                print(search)
                return render_template("dataentry.html", food_name=search)
                # return redirect(url_for('addfood',food_name=search))
        else: #if not given a dining hall request or a mealtype request
            menu = menuUp.lookupMenuList(conn, today()[0])
        names = ['', 'Bates', 'Lulu', 'Pom', 'Stone-D', 'Tower']
        return render_template('menu.html',date=today()[1], location = dhName, type = mealtype, menu = menu, title ="Menu", waitTime = waitTime, dh = dh, preferences = preference, names =names)

#for beta: how do I pass in the fid for processing too? 
@app.route('/autocomplete',methods=['GET'])
def autocomplete():
    conn = dbi.connect()
    # keyword to search: q is from jQuery, looking for 'q'
    search=request.args.get('q')
    # returns a list of dictionary of fid and food name
    dishes=menuUp.searchMenu(conn,search)
    #gets only the food name list 
    results=[entry["name"] for entry in dishes]
    # jsonify makes the list of food names in a JavaScript format
    return jsonify(matching_results=results)

@app.route('/food/<int:fid>', methods=["GET", "POST"])
def food(fid):
    conn = dbi.connect()
    if request.method == 'GET':
        # dictionary containing a food's name, ingredients, preference, allergen, type
        item = menuUp.lookupFoodItem(conn, fid)
        #average rating and number of ratings given to a food item
        avgRating, totalRatings = menuUp.avgRating(conn, fid) 
        # list of dictionaries for each comment for a given food item and with the comment's rating and user
        comments = menuUp.lookupComments(conn, fid)
        filename = pic(fid)
        return render_template('food.html', food = item, comments = comments, fid = fid, rating = avgRating, title = item["name"], filename = filename)
    else:
        menuUp.updateLastServed(conn, fid, today()[0])
        return redirect(url_for('food', fid = fid))

@app.route('/updateFood/<int:fid>', methods=["GET","POST"])
# name, type, rating, description, preference, label
def updateFood(fid):
    conn = dbi.connect()
    if request.method == "GET":
        try: 
            username = session['username']
            item = menuUp.lookupFoodItem(conn, fid)
            return render_template('foodUpdate.html', food = item, title = ("Update " + item["name"]))
        except:
            flash("Please log in to update food")
            return redirect(url_for("create"))

    elif request.form.get("submit") == "update":
        try:
            ingredients = request.form["ingredients"]
            menuUp.updateFoodItem(conn, fid, ingredients)
            item = menuUp.lookupFoodItem(conn, fid)
            flash("Thank you for updating {}, we really appreciate it!".format(item['name']))
            avgRating, totalRatings = menuUp.avgRating(conn, fid)
            comments = menuUp.lookupComments(conn,fid)
            return render_template('food.html', food = item, comments = comments, fid = fid, rating = avgRating)
        except Exception as err:
            flash('Update failed {why}'.format(why=err))
            return render_template('foodUpdate.html', food = item, title = ("Update " + item["name"]))
    else:
        try:
            item = menuUp.lookupFoodItem(conn, fid)
            flash("Thank you for updating {}, we really appreciate it!".format(item['name']))
            avgRating, totalRatings = menuUp.avgRating(conn, fid)
            comments = menuUp.lookupComments(conn,fid)
            f = request.files['pic']
            user_filename = f.filename
            ext = user_filename.split('.')[-1]
            filename = secure_filename('{}.{}'.format(fid,ext))
            pathname = os.path.join(app.config['UPLOADS'],filename)
            f.save(pathname)
            curs = dbi.dict_cursor(conn)
            curs.execute(
                '''insert into foodPics(fid,filename) values (%s,%s)
                   on duplicate key update filename = %s''',
                [fid, filename, filename])
            conn.commit()
            flash('Upload successful.')
            return redirect(url_for('food', fid = fid))
        except Exception as err:
            flash('Update failed {why}'.format(why=err))
            item = menuUp.lookupFoodItem(conn, fid)
            return render_template('foodUpdate.html', food = item, title = ("Update " + item["name"]))

@app.route('/updateWait/<int:did>', methods=["GET","POST"])
def updateWait(did):
    '''Update waiting time at a given dining hall'''
    conn = dbi.connect()
    dh = menuUp.lookupDH(conn, did)[0]
    if request.method == "GET":
        return render_template('waittimeUpdate.html',did = did, dh = dh, title = ("Update " + dh + " Wait Time"))
    else:
        try:
            waittime = request.form["waittime"]
            menuUp.updateFoodItem(conn, did, waittime)
            flash("Thank you for updating {}'s wait time, we really appreciate it!".format(dh))
            return render_template('menu.html',date=today()[1], menu = menu, title ="Menu")
        except Exception as err:
            flash('Update failed {why}'.format(why=err))
            return render_template('waittimeUpdate.html', dh = dh, did = did, title = ("Update " + dh + " Wait Time"))

# Gigi's Stuff!!
@app.route('/create/', methods=["GET", "POST"]) 
def create():
    if request.method ==  "GET":
        return render_template('create.html', title="Login")
    else:
        username = request.form['username']
        passwd1 = request.form['password1']
        passwd2 = request.form['password2']
        conn = dbi.connect()
        # next helper function checks to see if username is already in database and prompts user to log in instead 
        if query.username_exists(conn, username): 
            flash('''This username already exists. If this is you, please log in.
                If not, please enter your Wellesley email username.''')
            return render_template('create.html', title="Login")
        
        # if username doesn't exist, user is added to database and can now log in
        else: 
            # checks to see if paswords match
            if passwd1 != passwd2:
                flash('passwords do not match. please try again.')
                return render_template('create.html')
            else:
                hashed = bcrypt.hashpw(passwd1.encode('utf-8'),
                                    bcrypt.gensalt())
                hashed_str = hashed.decode('utf-8')
                curs = dbi.cursor(conn)
                query.add_username(conn, username, passwd1, hashed_str) 
                session['username'] = username
                session['logged_in'] = True
                flash('Profile was created successfully! You can post, review and more!')
                return redirect(url_for('profile', username=username)) 

# allows user to log in
@app.route('/user_login/', methods=["GET", "POST"])
def user_login():
    if request.method ==  "GET":
        return render_template('create.html', title="Login")
    else:
        username = request.form['username'] 
        passwd = request.form['password'] 
        conn = dbi.connect()
        curs = dbi.dict_cursor(conn)
        # helper function checks to make sure username exists in database
        if query.is_admin(conn, username): 
            # query finds password saved in database to compare with user input
            curs.execute('''select username, hashed 
                                from student 
                                where username = %s;''', [username])
            user = curs.fetchone()
            # checks if user input matches password on file
            hashed = user['hashed']
            hashed2 = bcrypt.hashpw(passwd.encode('utf-8'),
                                    hashed.encode('utf-8'))
            hashed2_str = hashed2.decode('utf-8')
            if hashed2_str  == hashed:
                flash('Successfully logged in.')
                session['username'] = username
                session['logged_in'] = True
                info =  query.get_user_info(conn, username)
                return redirect(url_for('profile', username=session['username'], info=info))
            else:
                flash('Incorrect login. Please try again.')
                return redirect(url_for('user_login'))
        else:
            flash("Only administrators can use this form. Please login through Wellesley portal.")
            return render_template('create.html', title="Login")

# allows user to see their profile
# how to get actual text instead of values for DH and Classyear 
@app.route('/profile/<username>', methods=['GET','POST'])
def profile(username):
    conn = dbi.connect()
    curs = dbi.cursor(conn)
    curs.execute('''select filename from proPics where username = %s''',[username])
    filename = curs.fetchone()
    try: 
        username = session['username']
        info =  query.get_user_info(conn, username)
        if request.method == "GET":
            diningHall = info['favoriteDH']
            reviews=feed_queries.user_reviews(conn,username)
            if diningHall == None:
                return render_template('profile.html', username=username, info=info, dh_name=diningHall, title="Your Profile", filename=filename,reviews=reviews)
            else:
                dh_name = query.DH_name(conn, diningHall)
                DH = dh_name['name']
                return render_template('profile.html', username=username, info=info, dh_name=DH, title="Your Profile", filename=filename,reviews=reviews)
        else:
            if request.form['submit'] == 'upload':
                f = request.files['pic']
                user_filename = f.filename
                ext = user_filename.split('.')[-1]
                filename = secure_filename('{}.{}'.format(username,ext))
                pathname = os.path.join(app.config['UPLOADS'],filename)
                f.save(pathname)
                curs = dbi.dict_cursor(conn)
                curs.execute(
                '''insert into proPics(username,filename) values (%s,%s)
                    on duplicate key update filename = %s''',
                    [username, filename, filename])
                conn.commit()
                flash("Upload successful. (If you don't see your new profile picture, hold down shift and refresh your page.")
                return render_template('profile.html', username=username, info=info, title="Your Profile", filename=filename)
        return render_template('profile.html', username=username, info=info, title="Your Profile", filename=filename)
    except Exception as err:
            flash('Update failed {why}'.format(why=err))
            return redirect(url_for('create'))
    # except:
    #     flash('Please log in to continue.') 
    #     session['username'] = ""
    #     session['logged_in'] = False
    #     return redirect(url_for('create'))

        
@app.route('/update/<username>', methods = ["GET", "POST"])
def update(username):
    # try:
        username = session['username']
        conn = dbi.connect()
        info =  query.get_user_info(conn, username)
        if request.method == "GET":
            info = query.get_user_info(conn, username)
            name = info['name']
            year = info['classYear']        
            diningHall = info['favoriteDH']
            if diningHall == None:
                return render_template('update.html', username=username, info=info, dh_name=diningHall, title="Your Profile")
            else:
                dh_name = query.DH_name(conn, diningHall)
                DH = dh_name['name']
                favoriteFood = info['favoriteFood']
                allergens  = info['allergies']
                preferences =  info['preferences']
                names = ['', 'Bates', 'Lulu', 'Pom', 'Stone-D', 'Tower']
                return render_template('update.html', username=username, info=info, dh_name=DH, title="Update Profile", names=names)
        elif request.form["submit"] == "update":
            if  request.method == 'POST':
                name2 = request.form['name']
                year2 = request.form['year']
                diningHall2 = request.form['diningHall']
                dh_name = query.DH_name(conn, diningHall2)
                DH = dh_name['name']
                favoriteFood2 = request.form['favoriteFood']
                allergens = request.form.getlist('allergens')
                str_all = ", ".join(allergens)
                preferences = request.form.getlist('preferences')  
                str_pref = ", ".join(preferences)
                query.update_profile(conn, username, name2, year2, diningHall2, favoriteFood2, str_all, str_pref)
                info = query.get_user_info(conn, username)
                flash("Successfully updated your profile!")
                return redirect(url_for('profile', 
                                username=username, 
                                info=info,
                                cas_attributes = session.get('CAS_ATTRIBUTES'),
                                dh_name=diningHall2,
                                allergens=allergens))
            else: 
                flash('Update failed {why}'.format(why=err))
                return render_template('update.html', username=username, info=info, title="Update Profile")
    # except Exception as err:
    #         flash('Update failed {why}'.format(why=err))
    #         return 
    # except:
    #     flash('Please log in to update your profile.') 
    #     return redirect(url_for('create'))

@app.route('/user_logout')
def user_logout():
    session.pop('username', None)
    session['logged_in'] = False
    return redirect(url_for('cas.logout'))

@app.route('/propic/<username>') 
#route to image for food photos, can later be generalized and applied to other photos too
def propic(username):
    conn = dbi.connect()
    curs = dbi.cursor(conn)
    sql = '''select filename from proPics where username = %s'''
    curs.execute(sql, [username])
    try:
        filename = curs.fetchone()[0]
        return send_from_directory(app.config['UPLOADS'],filename)
    except: #in the case when there is not yet a photo uploaded
        flash("This user either doesn't exist or doesn't have a profile picture")
        return redirect(url_for('profile', username=username))

@app.route('/profile/', methods = ["GET", "POST"])
def profile_error():
    if 'CAS_USERNAME' in session: 
        #check to see if logging in using CAS
        #if in database:
        username = session['CAS_USERNAME']
        session['username'] = username
        conn = dbi.connect()
        curs = dbi.cursor(conn)
        if query.username_exists(conn, username):
            return redirect(url_for('profile', username=username))
        else:
            flash("Looks like you're new here. Your account has just been created. Welcome to Foodie.!")
            query.add_username(conn, username, "NONE", "NONE")
            return redirect(url_for('profile', username=username))
    elif 'username' in session: 
        #if in database:
        conn = dbi.connect()
        curs = dbi.cursor(conn)
        username = session['username']
        if query.username_exists(conn, username):
            return redirect(url_for('profile', username=username))
        else:
            return redirect(url_for('create'))
    else:
        flash('Please log in.')
        return redirect(url_for('create'))


@app.route('/update/', methods = ["GET", "POST"])
def username_error():
    if 'username' in session: 
        conn = dbi.connect()
        curs = dbi.cursor(conn)
        username = session['username']
        if query.username_exists(conn, username):
            return redirect(url_for('update', username=username))
    else:
        flash("Please log in to update your profile2.")
        return render_template('create.html', title="Login")


@app.route('/user/<user>', methods= ['POST', "GET"])
def user(user):
    # allows user to look at other people's profile
    conn = dbi.connect()
    curs = dbi.cursor(conn)
    curs.execute('''select filename from proPics where username = %s''',[user])
    filename = curs.fetchone()
    reviews=feed_queries.user_reviews(conn,user)
    try: 
        username = session['username']
        info = query.get_user_info(conn, user)
        name = info['name']
        year = info['classYear']        
        diningHall = info['favoriteDH']
        if diningHall == None:
            return render_template('user.html', username=username, info=info, dh_name=diningHall, title="Your Profile", filename= filename, reviews=reviews)
        else:
            dh_name = query.DH_name(conn, diningHall)
            DH = dh_name['name']
            favoriteFood = info['favoriteFood']
            allergens  = info['allergies']
            preferences =  info['preferences']
            return render_template('user.html', username=user, info=info, dh_name=DH, title="Update Profile", filename= filename, reviews=reviews)
    except:
        flash("Please log in to view other profiles.")
        return redirect(url_for('create'))



# Fangwen's Part
## Here's the route to entering a feedback form
@app.route('/reviews/<int:fid>',methods=['POST','GET'])
def reviews(fid):
    conn=dbi.connect()
    if request.method=='GET':
        # get the form to display 
        try: 
            username = session['username']
            name=feed_queries.search_fid(conn,fid)['name']
            title="Reviews"
            return render_template('feed.html',title=title,name=name, fid = fid, username=username)
        except:
            flash("Please log in to add a review")
            return redirect(url_for("create"))
    else:
        # get the input form values from the submitted form
        username = session['username']
        rating=request.form['rating']
        comment=request.form['comment']
        time=datetime.now()
        #checking duplicate feedback on one dish published by one person
        if len(feed_queries.feedback_duplicate(conn,fid,username))!=0: 
            flash("You have already commented on this food, Please try commenting on another one.")
            return redirect(url_for('feed'))
        # stored form info into the database here
        feed_queries.feedback(conn,username,fid,rating,comment,time)
        return redirect(url_for('feed'))

@app.route('/feed/')     
def feed(): 
    conn=dbi.connect()
    feedbacks= feed_queries.recent_feedback(conn)
    top_rated=feed_queries.food_rating(conn)
    for item in top_rated:
        item['avg']=str(item['avg'])
    title='Feed'
    return render_template('reviews.html',feedbacks=feedbacks,ranking=top_rated, title=title)

# Leah's code

# NOTE: the query.is_admin function returns the opposite result of what's expected (i.e. false when it should be true) in my code 
# for some reason. I mitigated this by negating query.is_admin(...) in the addfood(), delete() and adminFoodUpdate() functions


# route for adding a food item to the database (inserts the food item into the food & labels tables)
# Note: because I made my insert statements thread-safe, they don't protect against duplicates
# while it should protect against exact duplicates, if a user enters in a dish that already exists in the same dining hall on a different date, 
# then it will still be added to the database because the 'lastServed' is different. 
@app.route('/addfood/', methods=["GET", "POST"])
def addfood():
    # redirects user to login page if they are not logged in 
    try: 
        username = session['username']
        if request.method == 'GET':
            return render_template('dataentry.html',title='Add Food')
        elif request.method == 'POST':
            conn = dbi.connect()
            food_name = request.form.get('food-name') 
            food_category = request.form.get('food-type')
            food_hall = request.form.get('food-hall')
            food_preferences = request.form.getlist('preferences')
            food_allergens = request.form.getlist('allergens')
            food_ingredients = request.form.get('food-ingredients')

            # error-handling: if any of the form elements aren't filled out, don't submit the form
            if len(food_name)==0: 
                flash("Please enter in the name of the food.")
                return render_template('dataentry.html',title='Add Food')
            if len(food_ingredients) == 0: 
                flash("Please enter in the food's ingredients.")
                return render_template('dataentry.html',title='Add Food')
            if len(food_preferences) == 0 or len(food_allergens) == 0: 
                flash("Please make sure that all boxes in the form are checked.")
                return render_template('dataentry.html',title='Add Food')
            
            # # not thread-safe, but duplicate-checking works
            # test_bool = entry.exists(conn,food_name,food_hall)
            # if test_bool == True: 
            #     flash("Food already exists in database.")
            #     return redirect(url_for("mainmenu"))
            
            # inserts food and associated label into table in a hopefully thread-safe way. duplicate checking doesn't work
            try: 
                food_date = today()[0]
                entry.insert_food(conn,food_name,food_date,food_category,food_hall)
                entry.insert_label(conn,food_allergens,food_preferences,food_ingredients)
                success_message = "{fname} was successfully inserted into the foodie database".format(fname=food_name) #doesn't successfully defend against duplicates. 
                flash(success_message)
                return redirect(url_for("mainmenu"))
            except pymysql.IntegrityError as err: 
               flash('Unable to insert {} due to {}'.format(name,repr(err)))
               return render_template('dataentry.html',title='Add Food')
    except:
        flash("Please login before accessing the add food page")
        return redirect(url_for('user_login'))

# route for deleting a food or comment from the database
@app.route('/delete/', methods=["GET", "POST"]) 
def delete(): 
    # check if user is logged in before allowing access to delete food webpage
    try:
        username = session['username']
        conn = dbi.connect()
        if request.method == "GET": 
            # retrieves food and comments from database
            all_foods = entry.get_all_food(conn) 
            all_comments = entry.get_all_comments(conn,username)

            # the 'entered' DateTime object, when added as an value/id element on the webpage, naturally has spaces in it. 
            # this is bad for HTML validation, so I am changing the formatting of the date here.
            # I am iterating through the dictionary of comments, and manually replacing the DateTime object with one that 
            # is seperated by dashes instead of spaces, so once a comment is added to the webpage, it will 
            # be in the YYYY-MM-DD-HH-MM-SS format, and not seperated by spaces. 

            for i in all_comments: 
                val = i['entered']
                i['entered'] = val.strftime("%Y-%m-%d-%H-%M-%S")
            return render_template('delete.html', title = 'Delete Food', allfoods=all_foods,comments=all_comments)
        
        if request.method == "POST":
            print('hello')
            food_id = request.form.get('food-dlt')
            comment_entered = request.form.get('comment-dlt') 
            print(food_id,comment_entered)
            
            # check if a user is an admin: 
            # error handling (if food isn't selected, or user isn't part of team foodie)
            # note: because the user can select a food item OR a comment to delete, it doesn't make 
            # sense to require both to be selected. 
            if food_id == 'none' and comment_entered == 'none': 
                flash('Please make sure you have selected a food item or comment to delete.')
                return redirect(url_for('delete'))
            elif query.is_admin(conn,username) and comment_entered != none:   
                flash('Sorry, you are not authorized to delete food items from the foodie database.')
                return redirect(url_for('home'))
            print('doing good!')

            # I think this is thread-safe, obtaining the food item's name isn't dependent on anything else
            if food_id != 'none': 
                food_name = entry.get_food(conn,food_id)
                print(food_name) 
            # deletes comments, labels and food table entries associated with a specific food item
                entry.delete_comments(conn,food_id) 
                entry.delete_labels(conn,food_id)
                entry.delete_food(conn,food_id)
                flash('{fname} was successfully deleted from the foodie database.'.format(fname=food_name))
            if comment_entered != "none": 
                entry.delete_comment(conn,username,comment_entered)
                flash('Your comment was successfully deleted from the foodie database')
            return redirect(url_for('home'))
    except:
        flash("Please login before accessing the delete food page")
        return redirect(url_for('user_login'))

#updates a food item's allergens & preferences, a task an admin can only do. 
@app.route('/adminFoodUpdate/', methods=["POST"]) 
def adminFoodUpdate(): 
    username = session['username']
    print('username',username)
    print(type(username))
    conn = dbi.connect()
    truth_bool = query.is_admin(conn,username)
    print('boolean returned',truth_bool,query.is_admin(conn,username))
    if not query.is_admin(conn,username): 
        if request.method == "POST": 
            food_preferences = request.form.getlist('preferences')
            food_allergens = request.form.getlist('allergens')
            food_id = request.form.get('food-update')
            print("food info: ",food_preferences,food_allergens,food_id)
            entry.updateFoodLabel(conn,food_allergens,food_preferences,food_id)
            flash('You successfully updated a food item.')
            return redirect(url_for('home'))
    else: 
        flash('Unfortunately, you are not an administrator and therefore not allowed to update the allergens & preferences associated w/ a food item.')
        return redirect(url_for('home')) 


     
@app.before_first_request
def init_db():
    dbi.cache_cnf()
    dbi.use('foodie_db')  

if __name__ == '__main__':
    import sys, os
    if len(sys.argv) > 1:
        # arg, if any, is the desired port number
        port = int(sys.argv[1])
        assert(port>1024)
    else:
        # port = os.getuid()
        port = 7739
    app.debug = True
    app.run('0.0.0.0',port)
