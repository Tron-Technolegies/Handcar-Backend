import json
import uuid
import jwt
import logging
from datetime import datetime, timedelta
from urllib.parse import quote
import random

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import IntegrityError
from django.db.models import Q
from django.http import (
    JsonResponse,
    HttpResponse,
    HttpResponseBadRequest,
)
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.views.decorators.csrf import csrf_exempt
from cloudinary.uploader import upload, destroy
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
import re
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import (
    AccessToken,
    RefreshToken,
    OutstandingToken,
    BlacklistedToken,
)
from rest_framework_simplejwt.exceptions import TokenError

from twilio.rest import Client
from geopy.exc import GeocoderTimedOut
from cloudinary.uploader import upload

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

# Local imports
from .authentication import CustomJWTAuthentication
from .models import (
    Product,
    Category,
    Brand,
    Coupon,
    Order,
    Plan,
    Subscriber,
    Subscription,
    CartItem,
    WishlistItem,
    Review,
    Address,
    Services,
    ServiceCategory,
    ServiceImage,
    ServiceInteractionLog,
    Service_Rating,
    PasswordResetOTP,
)
from .utils import (
    haversine,
    geocode_address,
    get_geocoded_location,
    get_nearby_vendors,
)

@csrf_exempt
def signup(request):
    if request.method == 'POST':
        # Parse JSON data from the request body
        try:
            data = json.loads(request.body)
            name = data.get('name')
            email = data.get('email')
            phone = data.get('phone')
            password = data.get('password')
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON format'}, status=400)

        # Check if all fields are provided
        if not all([name, email, phone, password]):
            return JsonResponse({'error': 'All fields are required'}, status=400)

        # Validate email format
        try:
            validate_email(email)
        except ValidationError:
            return JsonResponse({'error': 'Invalid email format'}, status=400)

        # Check if the email already exists
        if User.objects.filter(email=email).exists():
            return JsonResponse({'error': 'Email is already taken'}, status=400)

        # Check if the phone number is already registered
        if User.objects.filter(username=phone).exists():
            return JsonResponse({'error': 'Phone number is already registered'}, status=400)

        # Create the user
        try:
            user = User.objects.create_user(
                username=phone,
                first_name=name,
                email=email,
                password=password
            )
        except Exception as e:
            return JsonResponse({'error': f'Failed to create user: {str(e)}'}, status=500)

        return JsonResponse({'message': 'Signup successful!'}, status=201)

    return JsonResponse({'error': 'Invalid request method'}, status=405)


@csrf_exempt
def send_otp(request):
    if request.method == 'POST':
        phone_number = request.POST.get('phone')  # Get the phone number from the request

        if not phone_number:
            return JsonResponse({'error': 'Phone number is required'}, status=400)

        try:
            # Initialize Twilio client
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

            # Generate the OTP
            otp = generate_otp()
            message_body = f"Your OTP code is {otp}"

            # Send the OTP via Twilio
            message = client.messages.create(
                body=message_body,
                from_=settings.TWILIO_PHONE_NUMBER,
                to=phone_number
            )

            # Return success response with the message SID
            return JsonResponse({'message': 'OTP sent successfully', 'sid': message.sid}, status=200)

        except Exception as e:
            # Handle any errors and return a failure response
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request method'}, status=405)


def generate_otp(length=6):
    """Generates a random OTP of the given length"""
    return ''.join([str(random.randint(0, 9)) for _ in range(length)])

# Store OTP in cache for 5 minutes (300 seconds)
OTP_EXPIRATION_TIME = 300  # 5 minutes

def store_otp(phone, otp):
    """Stores the OTP in cache with expiration"""
    cache.set(phone, otp, timeout=OTP_EXPIRATION_TIME)

def verify_otp(phone, entered_otp):
    """Verifies if the entered OTP matches the stored one"""
    stored_otp = cache.get(phone)  # Retrieves the stored OTP from cache
    if stored_otp and stored_otp == entered_otp:
        # OTP is correct, remove it from the cache after verification
        cache.delete(phone)
        return True
    return False



# View for logging in with OTP  NOT WORKING- SHOWING INVALID OTP ERROR
@csrf_exempt
def login_with_otp(request):
    if request.method == 'POST':
        phone = request.POST.get('phone')
        entered_otp = request.POST.get('otp')

        # Verify OTP
        if verify_otp(phone, entered_otp):
            # Log in the user by phone number, assuming phone is the username
            try:
                user = User.objects.get(username=phone)
                login(request, user)
                return JsonResponse({'message': 'Login successful!'}, status=200)
            except User.DoesNotExist:
                return JsonResponse({'error': 'User does not exist'}, status=404)
        else:
            return JsonResponse({'error': 'Invalid OTP'}, status=400)

    return JsonResponse({'error': 'Invalid request method'}, status=405)




@csrf_exempt
def view_products(request):
    if request.method == 'GET':
        search_query = request.GET.get('search', '')
        category = request.GET.get('category', '')
        brand = request.GET.get('brand', '')
        min_price = request.GET.get('min_price', '')
        max_price = request.GET.get('max_price', '')
        sort_order = request.GET.get('sort', '')  # 'asc' or 'desc'

        products = Product.objects.all()

        # Filter by search query
        if search_query:
            products = products.filter(name__icontains=search_query)

        #  Multi-category filter (comma-separated)
        if category:
            category_list = [c.strip() for c in category.split(',')]
            products = products.filter(category__name__in=category_list)

        #  Multi-brand filter (comma-separated)
        if brand:
            brand_list = [b.strip() for b in brand.split(',')]
            products = products.filter(brand__name__in=brand_list)

        # Filter by price range
        if min_price:
            products = products.filter(price__gte=min_price)
        if max_price:
            products = products.filter(price__lte=max_price)

        # Sorting by price
        if sort_order == 'asc':
            products = products.order_by('price')
        elif sort_order == 'desc':
            products = products.order_by('-price')

        # Prepare response data
        data = [
            {
                "id": product.id,
                "name": product.name,
                "category": product.category.name if product.category else None,
                "brand": product.brand.name if product.brand else None,
                "price": product.price,
                "stock": product.stock,
                "image": product.image if product.image else None,
                "description": product.description,
                "discount_percentage": product.discount_percentage,
                "is_bestseller": product.is_bestseller,
                "average_rating": round(
                sum(review.rating for review in product.reviews.all()) / product.reviews.count(), 1
                ) if product.reviews.exists() else 0,
                "total_reviews": product.reviews.count(),
            }
            for product in products
        ]

        return JsonResponse({"product": data}, safe=False)

    return JsonResponse({'error': 'Invalid request method'}, status=400)

# Custom JWT Authentication to handle token from HttpOnly cookies

#
# class CustomJWTAuthentication(JWTAuthentication):
#     def authenticate(self, request):
#         # Retrieve the token from the cookie using the name specified in settings.py
#         token = request.COOKIES.get(settings.SIMPLE_JWT['AUTH_COOKIE'])
#         if not token:
#             raise AuthenticationFailed('Authentication token not found in cookies')
#
#         # Use the standard JWTAuthentication method to decode and authenticate the token
#         return self.authenticate_credentials(token)
#
#     def authenticate_credentials(self, token):
#         """
#         Custom implementation of authenticate_credentials to handle the JWT token
#         passed from the cookie and verify the credentials.
#         """
#         try:
#             # Decode the JWT token using the secret key and algorithm defined in settings
#             payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
#
#             # Extract user information from the payload
#             user_id = payload.get('user_id')  # Ensure the user_id field is in your token's payload
#             if not user_id:
#                 raise AuthenticationFailed('User ID not found in token')
#
#             # Retrieve the user from the database
#             user = self.get_user(user_id)
#             if user is None:
#                 raise AuthenticationFailed('User not found')
#
#             # Return the authenticated user and the token
#             return (user, token)
#
#         except jwt.ExpiredSignatureError:
#             raise AuthenticationFailed('Token has expired')
#         except jwt.DecodeError:
#             raise AuthenticationFailed('Error decoding token')
#         except User.DoesNotExist:
#             raise AuthenticationFailed('User does not exist')
#         except Exception as e:
#             raise AuthenticationFailed(f'Authentication failed: {str(e)}')
#
#     def get_user(self, user_id):
#         """
#         Helper method to get the user by ID.
#         Adjust this method according to your project's User model.
#         """
#         from django.contrib.auth.models import User  # Or your custom user model
#         try:
#             return User.objects.get(id=user_id)
#         except User.DoesNotExist:
#             return None



class AddToCartView(APIView):
    # Specify authentication and permission classes
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, product_id):
        # The user is already authenticated via CustomJWTAuthentication
        user = request.user

        # Add to cart logic
        product = get_object_or_404(Product, id=product_id)
        cart_item, created = CartItem.objects.get_or_create(user=user, product=product)

        if not created:
            # If the item is already in the cart, increase the quantity
            cart_item.quantity += 1
            cart_item.save()

        return Response({"message": "Product added to cart", "cart_quantity": cart_item.quantity})


@csrf_exempt
@api_view(['POST'])
@authentication_classes([CustomJWTAuthentication])
@permission_classes([IsAuthenticated])
def add_to_wishlist(request, product_id):
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        wishlist_item, created = WishlistItem.objects.get_or_create(user=request.user, product=product)

        # Return a JSON response with a success message or redirect
        if created:
            return JsonResponse({'message': 'Product added to wishlist', 'product_id': product_id})
        else:
            return JsonResponse({'message': 'Product already in wishlist', 'product_id': product_id})

    # If not a POST request, return a 405 Method Not Allowed
    return JsonResponse({'error': 'Invalid request method'}, status=405)


@api_view(['GET'])
@authentication_classes([CustomJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_wishlist_items(request):
    try:
        wishlist_items = WishlistItem.objects.filter(user=request.user)
        
        response_data = []
        for item in wishlist_items:
            product = item.product
            response_data.append({
                'id': item.id,
                'product_id': product.id,
                'product_name': product.name,
                'product_price': product.price,
                'product_image': product.image if product.image else None,
                'product_description': product.description,
            })
        
        return Response({'wishlist_items': response_data}, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    

@api_view(['DELETE'])
@authentication_classes([CustomJWTAuthentication])
@permission_classes([IsAuthenticated])

def remove_wishlist(request,wishlist_id):
    try:
        Wishlist_item = WishlistItem.objects.get(user=request.user,id=wishlist_id,)
        Wishlist_item.delete()
        return Response({'message': 'Product removed from wishlist'}, status=status.HTTP_200_OK)
    except WishlistItem.DoesNotExist:
        return Response({'error': 'Product not found in wishlist'}, status=status.HTTP_404_NOT_FOUND)



def filter_by_category(queryset, category_id):
    return queryset.filter(category_id=category_id)

def filter_by_brand(queryset, brand_id):
    return queryset.filter(brand_id=brand_id)

def filter_by_aed(queryset, min_price=None, max_price=None):
    if min_price is not None:
        queryset = queryset.filter(price__gte=min_price)
    if max_price is not None:
        queryset = queryset.filter(price__lte=max_price)
    return queryset

def filter_by_new_arrivals(queryset, days=30):
    recent_date = timezone.now() - timedelta(days=days)
    return queryset.filter(created_at__gte=recent_date)

def filter_by_rating(queryset, min_rating):
    return queryset.filter(rating__gte=min_rating)

@csrf_exempt
def filter_and_search_products(request):
    products = Product.objects.all()

    # Get filter parameters
    search_query = request.GET.get('search')
    category_id = request.GET.get('category_id')
    brand_id = request.GET.get('brand_id')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    min_rating = request.GET.get('min_rating')
    new_arrivals = request.GET.get('new_arrivals')
    sort_by = request.GET.get('sort_by')

    # Apply search by name
    if search_query:
        products = products.filter(name__icontains=search_query)

    # Apply filters safely
    if category_id and category_id.isdigit():
        products = filter_by_category(products, int(category_id))

    if brand_id and brand_id.isdigit():
        products = filter_by_brand(products, int(brand_id))

    # Fixed price filter logic
    try:
        min_val = float(min_price) if min_price else None
        max_val = float(max_price) if max_price else None
        if min_val is not None or max_val is not None:
            products = filter_by_aed(products, min_val, max_val)
    except (ValueError, TypeError):
        pass  # Ignore price filter if invalid

    try:
        if min_rating:
            products = filter_by_rating(products, float(min_rating))
    except (ValueError, TypeError):
        pass

    if new_arrivals == 'true':
        products = filter_by_new_arrivals(products)

    # Apply sorting if provided
    if sort_by in ['price', '-price', 'rating', '-rating', 'created_at', '-created_at']:
        products = products.order_by(sort_by)

    # Prepare response - Fixed potential attribute errors
    product_data = []
    for product in products:
        product_info = {
            'id': product.id,
            'name': product.name,
            'price': product.price,
            'brand': product.brand.name if product.brand else None,
            'image_url': product.image.url if product.image and hasattr(product.image, 'url') else None,
            'description': product.description,
            'rating': product.rating,
        }
        product_data.append(product_info)

    return JsonResponse({'products': product_data})


logger = logging.getLogger(__name__)

@csrf_exempt
def subscribe(request):
    logger.info("subscribe view called")  # Log when the view is hit

    if request.method == 'POST':
        plan = request.POST.get('plan')
        category = request.POST.get('category')
        duration = request.POST.get('duration')

        if plan and category and duration:
            message = f"I would like to subscribe to the {plan} plan for {category} for {duration}."
            encoded_message = quote(message)
            whatsapp_url = f"https://wa.me/917025791186?text={encoded_message}"

            logger.info(f"Generated WhatsApp URL: {whatsapp_url}")  # Log the generated URL

            return JsonResponse({'whatsapp_url': whatsapp_url})
        else:
            logger.warning("Invalid subscription data")
            return HttpResponseBadRequest("Invalid subscription data.")

    logger.warning("Invalid request method")
    return HttpResponseBadRequest("Invalid request method.")


class DisplayCartView(APIView):
    # Specify authentication and permission classes
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # The user is already authenticated via CustomJWTAuthentication
        user = request.user

        # Get all cart items for the logged-in user
        cart_items = CartItem.objects.filter(user=user)

        # Prepare cart items data for JSON response
        cart_data = []
        for item in cart_items:
            cart_data.append({
                'cart_item_id': item.id,
                'product_id': item.product.id,
                'product_image': item.product.image,
                'product_name': item.product.name,
                'product_price': item.product.price,
                'quantity': item.quantity,
                'total_price': item.product.price * item.quantity,
            })

        # Calculate total price for the cart
        total_price = sum(item['total_price'] for item in cart_data)

        # Return response with cart items and total price
        return Response({
            'cart_items': cart_data,
            'total_price': total_price
        })



class UpdateCartItemView(APIView):
    """
    View to update the quantity of a cart item.
    """
    authentication_classes = [CustomJWTAuthentication]  # Add your authentication class here
    permission_classes = [IsAuthenticated]  # Ensure the user is authenticated

    def put(self, request, cart_item_id):
        try:
            cart_item = CartItem.objects.get(id=cart_item_id, user=request.user)

        except CartItem.DoesNotExist:
            return Response({"error": "Cart item not found"}, status=status.HTTP_404_NOT_FOUND)

        # Validate the new quantity
        new_quantity = request.data.get('quantity')
        if new_quantity is None or new_quantity <= 0:
            return Response({"error": "Invalid quantity"}, status=status.HTTP_400_BAD_REQUEST)

        # Update the quantity
        cart_item.quantity = new_quantity
        cart_item.save()

        return Response({"message": "Cart item updated successfully"}, status=status.HTTP_200_OK)


import logging
logger = logging.getLogger(__name__)

class RemoveCartItemView(APIView):
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request, item_id):
        try:
            logger.info(f"Received DELETE request for item_id: {item_id}")
            logger.info(f"Authenticated user: {request.user}")

            item_id = int(item_id)
            cart_item = CartItem.objects.get(id=item_id, user=request.user)
        except ValueError:
            logger.error(f"Invalid item_id: {item_id}")
            return Response({"error": "Invalid item ID"}, status=status.HTTP_400_BAD_REQUEST)
        except CartItem.DoesNotExist:
            logger.error(f"Cart item with id {item_id} not found for user {request.user}")
            return Response({"error": "Cart item not found"}, status=status.HTTP_404_NOT_FOUND)

        cart_item.delete()
        return Response({"message": "Item removed successfully"})


# @csrf_exempt
# @login_required
# def add_review(request, product_id):
#     product = get_object_or_404(Product, id=product_id)

#     # Parse JSON data from the request body
#     try:
#         data = json.loads(request.body)
#         rating = data.get('rating')
#         comment = data.get('comment')

#         # Validate that required fields are provided
#         if rating is None or not isinstance(rating, int) or not (1 <= rating <= 5):
#             return JsonResponse({'error': 'Rating must be an integer between 1 and 5.'}, status=400)

#         # Optional comment validation if needed
#         if comment and not isinstance(comment, str):
#             return JsonResponse({'error': 'Comment must be a string.'}, status=400)

#         # Attempt to create a new review
#         try:
#             review = Review.objects.create(
#                 product=product,
#                 user=request.user,
#                 rating=rating,
#                 comment=comment
#             )
#             return JsonResponse({'message': 'Review added successfully.', 'review_id': review.id}, status=201)

#         except IntegrityError:
#             return JsonResponse({'error': 'You have already reviewed this product. Please edit your existing review.'},
#                                 status=400)

#     except json.JSONDecodeError:
#         return JsonResponse({'error': 'Invalid JSON data.'}, status=400)
    

@api_view(['POST'])
@authentication_classes([CustomJWTAuthentication])
@permission_classes([IsAuthenticated])
def add_review(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    # Parse JSON data from the request body
    try:
        data = json.loads(request.body)
        rating = data.get('rating')
        comment = data.get('comment')

        # Validate that required fields are provided
        if rating is None or not isinstance(rating, int) or not (1 <= rating <= 5):
            return JsonResponse({'error': 'Rating must be an integer between 1 and 5.'}, status=400)

        # Optional comment validation if needed
        if comment and not isinstance(comment, str):
            return JsonResponse({'error': 'Comment must be a string.'}, status=400)

        # Attempt to create a new review
        try:
            review = Review.objects.create(
                product=product,
                user=request.user,
                rating=rating,
                comment=comment
            )
            return JsonResponse({'message': 'Review added successfully.', 'review_id': review.id}, status=201)

        except IntegrityError:
            return JsonResponse({'error': 'You have already reviewed this product. Please edit your existing review.'},
                                status=400)

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data.'}, status=400)
    
@csrf_exempt
def view_review(request, product_id):
    if request.method == 'GET':
        product = get_object_or_404(Product, id=product_id)
        reviews = Review.objects.filter(product=product)
        review_data = []
        for review in reviews:
            review_data.append({
                'id': review.id,
                'user': review.user.first_name,
                'rating': review.rating,
                'comment': review.comment,
            })
        return JsonResponse({'reviews': review_data}, status=200)
    if not reviews.exists():
        return JsonResponse({'message': 'No reviews for this product'}, status=200)

    else:
        return JsonResponse({'error': 'Invalid HTTP method.'}, status=405)

@csrf_exempt
def add_category(request):
    if request.method == 'POST':
        try:
            # Check if the request body exists
            if not request.body:
                return JsonResponse({"error": "Request body is empty"}, status=400)

            # Attempt to parse JSON
            data = json.loads(request.body)

            # Extract fields
            name = data.get('name')


            # Validate required fields
            if not name:
                return JsonResponse({"error": "Name is required"}, status=400)

            # Create the category
            category = Category.objects.create(name=name)
            return JsonResponse({"id": category.id, "name": category.name},
                                status=201)

        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON format"}, status=400)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid HTTP method"}, status=405)


def view_categories(request):
    if request.method == 'GET':
        search_query = request.GET.get('search', '')
        if search_query:
            categories = Category.objects.filter(name__icontains=search_query)
        else:
            categories = Category.objects.all()
        data = [{"id": cat.id, "name": cat.name} for cat in categories]
        return JsonResponse({"categories": data}, safe=False)

@csrf_exempt
def edit_category(request, category_id):
    # Retrieve the category instance by ID
    category = get_object_or_404(Category, id=category_id)

    if request.method == 'GET':
        # Return the current category details as JSON
        return JsonResponse({
            "id": category.id,
            "name": category.name,
        })


    elif request.method == 'POST':
        # Get the updated name from the request body
        try:
            data = request.POST
            new_name = data.get('name')

            if not new_name:
                return JsonResponse({"error": "Name is required"}, status=400)

            # Update and save the category
            category.name = new_name
            category.save()

            return JsonResponse({
                "message": "Category updated successfully",
                "id": category.id,
                "name": category.name,
            })
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    else:
        return JsonResponse({"error": "Invalid HTTP method"}, status=405)


@csrf_exempt
def delete_category(request, category_id):
    if request.method == 'DELETE':
        try:
            # Retrieve the category instance by ID
            category = get_object_or_404(Category, id=category_id)

            # Delete the category
            category.delete()

            return JsonResponse({"message": "Category deleted successfully"}, status=200)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Invalid HTTP method"}, status=405)


@csrf_exempt
def add_brand(request):
    if request.method == 'POST':
        try:
            # Check if the request body exists
            if not request.body:
                return JsonResponse({"error": "Request body is empty"}, status=400)

            # Attempt to parse JSON
            data = json.loads(request.body)

            # Extract fields
            name = data.get('name')


            # Validate required fields
            if not name:
                return JsonResponse({"error": "Name is required"}, status=400)

            # Create the Brand
            brands = Brand.objects.create(name=name)
            return JsonResponse({"id": brands.id, "name": brands.name},status=201)

        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON format"}, status=400)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid HTTP method"}, status=405)


def view_brand(request):
    if request.method == 'GET':
        search_query = request.GET.get('search', '')
        if search_query:
            brands = Brand.objects.filter(name__icontains=search_query)
        else:
            brands = Brand.objects.all()
        data = [{"id": brand.id, "name": brand.name} for brand in brands]
        return JsonResponse({"brands": data}, safe=False)


@csrf_exempt
def edit_brand(request, brand_id):
    # Retrieve the category instance by ID
    brand = get_object_or_404(Brand, id=brand_id)

    if request.method == 'GET':
        # Return the current category details as JSON
        return JsonResponse({
            "id": brand.id,
            "name": brand.name,
        })

    elif request.method == 'POST':
        # Get the updated name from the request body
        try:
            data = request.POST
            new_name = data.get('name')

            if not new_name:
                return JsonResponse({"error": "Name is required"}, status=400)

            # Update and save the brand
            brand.name = new_name
            brand.save()

            return JsonResponse({
                "message": "Brand updated successfully",
                "id": brand.id,
                "name": brand.name,
            })
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    else:
        return JsonResponse({"error": "Invalid HTTP method"}, status=405)


@csrf_exempt
def delete_brand(request, brand_id):
    if request.method == 'DELETE':
        try:
            # Retrieve the category instance by ID
            brand = get_object_or_404(Brand, id=brand_id)

            # Delete the category
            brand.delete()

            return JsonResponse({"message": "Brand deleted successfully"}, status=200)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Invalid HTTP method"}, status=405)





@csrf_exempt
def add_product(request):
    if request.method == 'POST':
        try:
            # Check if the request contains image file
            image_file = request.FILES.get('image')

            # Get other data from the form (strings from POST)
            name = request.POST.get('name')
            category_name = request.POST.get('category_name')
            brand_name = request.POST.get('brand_name')
            price = request.POST.get('price')
            description = request.POST.get('description', '')
            stock = request.POST.get('stock')
            is_bestseller = request.POST.get('is_bestseller', 'false').lower() == 'true'  # Convert to bool
            discount_percentage = request.POST.get('discount_percentage', '0')

            # Validate required fields are present
            if not all([name, category_name, brand_name, price, stock]):
                return JsonResponse({
                    "error": "Name, category_name, brand_name, price, and stock are required."
                }, status=400)

            # Convert numeric fields to proper types
            try:
                price = float(price)
            except ValueError:
                return JsonResponse({"error": "Price must be a valid number."}, status=400)

            try:
                stock = int(stock)
            except ValueError:
                return JsonResponse({"error": "Stock must be a valid integer."}, status=400)

            try:
                discount_percentage = int(discount_percentage)
            except ValueError:
                discount_percentage = 0  # default to 0 if invalid

            # Retrieve related objects by name
            category = get_object_or_404(Category, name=category_name)
            brand = get_object_or_404(Brand, name=brand_name)

            # Handle image upload to Cloudinary
            image_url = None
            if image_file:
                try:
                    upload_result = upload(image_file, folder="product_images/")
                    image_url = upload_result['secure_url']
                except Exception as e:
                    return JsonResponse({"error": f"Image upload failed: {str(e)}"}, status=500)

            # Create the Product instance with validated/converted values
            product = Product.objects.create(
                name=name,
                category=category,
                brand=brand,
                price=price,
                description=description,
                stock=stock,
                is_bestseller=is_bestseller,
                discount_percentage=discount_percentage,
                image=image_url
            )

            return JsonResponse({
                "message": "Product added successfully.",
                "product": {
                    "id": product.id,
                    "name": product.name,
                    "category": product.category.name,
                    "brand": product.brand.name,
                    "price": str(product.price),
                    "description": product.description,
                    "stock": product.stock,
                    "is_bestseller": product.is_bestseller,
                    "discount_percentage": product.discount_percentage,
                    "image": product.image,
                    "created_at": product.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                }
            }, status=201)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid HTTP method."}, status=405)

#
# @csrf_exempt
# def view_products(request):
#     if request.method == 'GET':
#         search_query = request.GET.get('search', '')
#         if search_query:
#             products = Product.objects.filter(name__icontains=search_query)
#         else:
#             products = Product.objects.all()
#         data = [{"id": product.id,
#                  "name": product.name,
#                  "category": product.category.name,
#                  "brand": product.brand.name,
#                  "price": product.price,
#                  "image": product.image,
#                  "description": product.description,
#                  "discount_percentage": product.discount_percentage} for product in products]
#         return JsonResponse({"product": data}, safe=False)
#
#


# def edit_product(request, product_id):
#     if request.method == 'PUT':
#         try:
#             # Retrieve the product to be edited
#             product = get_object_or_404(Product, id=product_id)
#
#             # Parse JSON data
#             data = json.loads(request.body)
#
#             # Update fields if provided
#             product.name = data.get('name', product.name)
#             category_id = data.get('category_id')
#             if category_id:
#                 product.category = get_object_or_404(Category, id=category_id)
#             brand_id = data.get('brand_id')
#             if brand_id:
#                 product.brand = get_object_or_404(Brand, id=brand_id)
#                 product.price = data.get('price', product.price)
#                 product.description = data.get('description', product.description)
#                 product.is_bestseller = data.get('is_bestseller', product.is_bestseller)
#                 product.discount_percentage = data.get('discount_percentage', product.discount_percentage)
#
#             # Save the updated product
#             product.save()
#
#             return JsonResponse({"message": "Product updated successfully."}, status=200)
#
#         except Exception as e:
#             return JsonResponse({"error": str(e)}, status=500)
#
#     return JsonResponse({"error": "Invalid HTTP method."}, status=405)


@csrf_exempt
def edit_product(request, product_id):
    if request.method == 'GET':
        product = get_object_or_404(Product, id=product_id)
        product_data = {
            "id": product.id,
            "name": product.name,
            "category_name": product.category.name if product.category else None,
            "brand_name": product.brand.name if product.brand else None,
            "price": product.price,
            "stock": product.stock,
            "description": product.description,
            "is_bestseller": product.is_bestseller,
            "discount_percentage": product.discount_percentage,
            "image": product.image
        }
        return JsonResponse(product_data, status=200)

    elif request.method == 'POST':
        try:
            product = get_object_or_404(Product, id=product_id)

            image_file = request.FILES.get('image', None)
            image_url = product.image  # Default to current image

            # If a new image is uploaded
            if image_file:
                # Delete the old image from Cloudinary
                if product.image:
                    try:
                        match = re.search(r'product_images/([^\.]+)', product.image)
                        if match:
                            public_id = f"product_images/{match.group(1)}"
                            destroy(public_id)
                    except Exception as e:
                        return JsonResponse({"error": f"Failed to delete old image: {str(e)}"}, status=500)

                # Upload new image to Cloudinary
                try:
                    upload_result = upload(image_file, folder="product_images/")
                    image_url = upload_result['secure_url']
                except Exception as e:
                    return JsonResponse({"error": f"Image upload failed: {str(e)}"}, status=500)

            # Get form data
            name = request.POST.get('name', product.name)
            category_name = request.POST.get('category_name', product.category.name if product.category else '')
            brand_name = request.POST.get('brand_name', product.brand.name if product.brand else '')
            price = request.POST.get('price', product.price)
            stock = request.POST.get('stock', product.stock)
            description = request.POST.get('description', product.description)
            is_bestseller = request.POST.get('is_bestseller', product.is_bestseller)
            discount_percentage = request.POST.get('discount_percentage', product.discount_percentage)

            # Validate required fields
            if not name or not category_name or not brand_name or not price:
                return JsonResponse({"error": "Name, category_name, brand_name, and price are required."}, status=400)

            category = get_object_or_404(Category, name=category_name)
            brand = get_object_or_404(Brand, name=brand_name)

            # Update product
            product.name = name
            product.category = category
            product.brand = brand
            product.price = price
            product.stock = stock
            product.description = description
            product.is_bestseller = is_bestseller
            product.discount_percentage = discount_percentage
            product.image = image_url
            product.save()

            return JsonResponse({
                "message": "Product updated successfully.",
                "product": {
                    "id": product.id,
                    "name": product.name,
                    "category": product.category.name,
                    "brand": product.brand.name,
                    "price": str(product.price),
                    "stock": product.stock,
                    "description": product.description,
                    "is_bestseller": product.is_bestseller,
                    "discount_percentage": product.discount_percentage,
                    "image": product.image,
                    "created_at": product.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                }
            }, status=200)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid HTTP method."}, status=405)


@csrf_exempt
def delete_product(request, product_id):
    if request.method == 'DELETE':
        try:
            product = get_object_or_404(Product, id=product_id)

            # Delete Cloudinary image
            if product.image:
                try:
                    match = re.search(r'product_images/([^\.]+)', product.image)
                    if match:
                        public_id = f"product_images/{match.group(1)}"
                        destroy(public_id)
                except Exception as e:
                    return JsonResponse({"error": f"Failed to delete image from Cloudinary: {str(e)}"}, status=500)

            product.delete()
            return JsonResponse({"message": "Product deleted successfully"}, status=200)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Invalid HTTP method"}, status=405)





@csrf_exempt
def add_coupon(request):
    if request.method == 'POST':
        try:
            # Parse JSON data from the request body
            data = json.loads(request.body)

            name = data.get('name')
            coupon_code = data.get('coupon_code')
            discount_percentage = data.get('discount_percentage')
            start_date = data.get('start_date')
            end_date = data.get('end_date')
            description = data.get('description')

            # Validate required fields
            if not name or not coupon_code or not discount_percentage or not start_date or not end_date or not description:
                return JsonResponse({"error": "All fields are required."}, status=400)

            # Create the vendor
            coupon = Coupon.objects.create(
                name=name,
                coupon_code=coupon_code,
                discount_percentage=discount_percentage,
                start_date=start_date,
                end_date = end_date,
                description = description
            )

            return JsonResponse({
                "message": "Coupon added successfully.",
                "coupon": {
                    "id": coupon.id,
                    "name": coupon.name,
                    "coupon_code": coupon.coupon_code,
                    "discount_percentage": coupon.discount_percentage,
                    "start_date": coupon.start_date,
                    "end_date": coupon.end_date,
                    "description": coupon.description
                }
            }, status=201)

        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON data."}, status=400)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid HTTP method."}, status=405)



@csrf_exempt
def view_coupons(request):
    if request.method == 'GET':
        search_query = request.GET.get('search', '')
        if search_query:
            coupons = Coupon.objects.filter(name__icontains=search_query)
        else:
            coupons = Coupon.objects.all()
        data = [{   "id": coupon.id,
                    "name": coupon.name,
                    "coupon_code": coupon.coupon_code,
                    "discount_percentage": coupon.discount_percentage,
                    "start_date": coupon.start_date,
                    "end_date": coupon.end_date,
                    "description": coupon.description} for coupon in coupons]
        return JsonResponse({"coupon": data}, safe=False)



# @csrf_exempt
# def edit_coupons(request, coupon_id):
#     if request.method == 'PUT':
#         try:
#             # Retrieve the vendor to be edited
#             coupons = get_object_or_404(Coupon, id=coupon_id)

#             # Parse JSON data
#             data = json.loads(request.body)

#             # Update fields if provided
#             coupons.name = data.get('name', coupons.name)
#             coupons.coupon_code = data.get('coupon_code', coupons.coupon_code)
#             coupons.discount_percentage = data.get('discount_percentage', coupons.discount_percentage)
#             coupons.start_date = data.get('start_date', coupons.start_date)
#             coupons.end_date = data.get('end_date', coupons.end_date)
#             coupons.description = data.get('description', coupons.description)

#             # Log the updated values
#             print("Updated Coupon Data:", coupons.name, coupons.coupon_code, coupons.discount_percentage)

#             # Save the updated coupon
#             coupons.save()

#             return JsonResponse({"message": "Coupon updated successfully."}, status=200)

#         except Exception as e:
#             return JsonResponse({"error": str(e)}, status=500)

#     return JsonResponse({"error": "Invalid HTTP method."}, status=405)



@csrf_exempt
def edit_coupons(request, coupon_id):
    try:
        coupon = get_object_or_404(Coupon, id=coupon_id)

        if request.method == 'GET':
            # Return existing coupon details
            return JsonResponse({
                "id": coupon.id,
                "name": coupon.name,
                "coupon_code": coupon.coupon_code,
                "discount_percentage": coupon.discount_percentage,
                "start_date": coupon.start_date.strftime("%Y-%m-%d") if coupon.start_date else None,
                "end_date": coupon.end_date.strftime("%Y-%m-%d") if coupon.end_date else None,
                "description": coupon.description,
            }, status=200)

        elif request.method == 'PUT':
            data = json.loads(request.body)

            coupon.name = data.get('name', coupon.name)
            coupon.coupon_code = data.get('coupon_code', coupon.coupon_code)
            coupon.discount_percentage = data.get('discount_percentage', coupon.discount_percentage)

            start_date = data.get('start_date')
            end_date = data.get('end_date')
            if start_date:
                coupon.start_date = datetime.strptime(start_date, "%Y-%m-%d")
            if end_date:
                coupon.end_date = datetime.strptime(end_date, "%Y-%m-%d")

            coupon.description = data.get('description', coupon.description)

            coupon.save()

            return JsonResponse({"message": "Coupon updated successfully."}, status=200)

        else:
            return JsonResponse({"error": "Invalid HTTP method."}, status=405)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
def delete_coupons(request, coupon_id):
    if request.method == 'DELETE':
        try:
            # Retrieve the coupon instance by ID
            coupon = get_object_or_404(Coupon, id=coupon_id)

            # Delete the coupon
            coupon.delete()

            return JsonResponse({"message": "Coupon deleted successfully"}, status=200)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Invalid HTTP method"}, status=405)


@csrf_exempt
def add_plan(request):
    if request.method == 'POST':
        try:
            # Parse JSON data from the request body
            data = json.loads(request.body)

            name = data.get('name')
            service_type = data.get('service_type')
            duration = data.get('duration')
            price = data.get('price')
            description = data.get('description')


            # Validate required fields
            if not name or not service_type or not duration or not price or not description:
                return JsonResponse({"error": "All fields are required."}, status=400)

            # Create the vendor
            plan = Plan.objects.create(
                name=name,
                service_type=service_type,
                duration=duration,
                price=price,
                description = description
            )

            return JsonResponse({
                "message": "Plan added successfully.",
                "coupon": {
                    "id": plan.id,
                    "name": plan.name,
                    "service_type": plan.service_type,
                    "duration": plan.duration,
                    "price": plan.price,
                    "description": plan.description
                }
            }, status=201)

        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON data."}, status=400)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid HTTP method."}, status=405)



@csrf_exempt
def view_plans(request):
    if request.method == 'GET':
        search_query = request.GET.get('search', '')
        if search_query:
            plans = Plan.objects.filter(name__icontains=search_query)
        else:
            plans = Plan.objects.all()
        data = [{  "id": plan.id,
                    "name": plan.name,
                    "service_type": plan.service_type,
                    "duration": plan.duration,
                    "price": plan.price,
                    "description": plan.description} for plan in plans]
        return JsonResponse({"plan": data}, safe=False)



# @csrf_exempt
# def edit_plan(request, plan_id):
#     if request.method == 'PUT':
#         try:
#             # Retrieve the plan to be edited
#             plans = get_object_or_404(Plan, id=plan_id)

#             # Parse JSON data
#             data = json.loads(request.body)

#             # Update fields if provided
#             plans.name = data.get('name', plans.name)
#             plans.service_type = data.get('service_type', plans.service_type)
#             plans.duration = data.get('duration', plans.duration)
#             plans.price = data.get('price', plans.price)
#             plans.description = data.get('description', plans.description)

#             # Save the updated plan
#             plans.save()

#             return JsonResponse({"message": "Coupon updated successfully."}, status=200)

#         except Exception as e:
#             return JsonResponse({"error": str(e)}, status=500)

#     return JsonResponse({"error": "Invalid HTTP method."}, status=405)

@csrf_exempt
def edit_plan(request, plan_id):
    try:
        # Fetch the plan object or return 404
        plan = get_object_or_404(Plan, id=plan_id)

        if request.method == 'GET':
            # Return existing plan details
            return JsonResponse({
                "id": plan.id,
                "name": plan.name,
                "service_type": plan.service_type,
                "duration": plan.duration,
                "price": float(plan.price),  # Ensure JSON serializable
                "description": plan.description,
            }, status=200)

        elif request.method == 'PUT':
            try:
                # Parse JSON data
                data = json.loads(request.body)

                # Update fields if provided
                plan.name = data.get('name', plan.name)
                plan.service_type = data.get('service_type', plan.service_type)
                plan.duration = data.get('duration', plan.duration)
                plan.price = data.get('price', plan.price)
                plan.description = data.get('description', plan.description)

                # Save changes
                plan.save()

                return JsonResponse({"message": "Plan updated successfully."}, status=200)

            except json.JSONDecodeError:
                return JsonResponse({"error": "Invalid JSON format."}, status=400)
            except Exception as e:
                return JsonResponse({"error": str(e)}, status=500)

        else:
            return JsonResponse({"error": "Method not allowed. Use GET or PUT."}, status=405)

    except Plan.DoesNotExist:
        return JsonResponse({"error": "Plan not found."}, status=404)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
def delete_plan(request, plan_id):
    if request.method == 'DELETE':
        try:
            # Retrieve the coupon instance by ID
            plan = get_object_or_404(Plan, id=plan_id)

            # Delete the coupon
            plan.delete()

            return JsonResponse({"message": "Plan deleted successfully"}, status=200)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Invalid HTTP method"}, status=405)

@csrf_exempt
def search_products(request):
    query = request.GET.get('query', '')  # Get the search query from the request
    products = Product.objects.filter(name__icontains=query)  # Filter products by name
    # You can add more filters like category or brand here
    results = [
        {
            "id": product.id,
            "name": product.name,
            "category": product.category.name,
            "brand": product.brand.name,
            "price": float(product.price),
            "promoted": product.promoted,
        }
        for product in products
    ]
    return JsonResponse({"products": results})


@csrf_exempt
def promote_product(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        product_id = data.get('product_id')
        product = get_object_or_404(Product, id=product_id)
        product.promoted = True  # Mark as promoted
        product.save()
        return JsonResponse({"message": "Product promoted successfully!", "promoted": True})
    return JsonResponse({"error": "Invalid request method"}, status=400)


def view_promoted_products(request):
    if request.method == 'GET':
        # Filter products where promoted is True
        promoted_products = Product.objects.filter(promoted=True)

        promoted_products_list = [
            {
                "id": product.id,
                "name": product.name,
                "category": product.category.name,
                "brand": product.brand.name,
                "price": str(product.price),
                "description": product.description,
                "is_bestseller": product.is_bestseller,
                "discount_percentage": product.discount_percentage,
                "image": product.image,
                "created_at": product.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            }
            for product in promoted_products
        ]

        return JsonResponse({"promoted_products": promoted_products_list}, status=200)

    return JsonResponse({"error": "Invalid request method"}, status=400)


@csrf_exempt
def remove_promoted_product(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)  # Parse the JSON request body
            product_id = data.get('product_id')  # Get the product ID from the request
            product = get_object_or_404(Product, id=product_id)  # Retrieve the product

            if product.promoted:  # Check if the product is currently promoted
                product.promoted = False  # Set promoted to False
                product.save()  # Save the updated product
                return JsonResponse({"message": "Product removed from promoted successfully!", "promoted": False})
            else:
                return JsonResponse({"message": "Product is not promoted.", "promoted": False})

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid request method"}, status=400)


def search_brands(request):
    query = request.GET.get('query','')
    brand = Brand.objects.filter(name__icontains=query)
    results = [
        {
            "id": brands.id,
            "name": brands.name,
            "promoted": brands.promoted,
        }
        for brands in brand
    ]
    return JsonResponse({"brand": results})

@csrf_exempt
def promote_brand(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        brand_id = data.get('brand_id')
        brand = get_object_or_404(Brand, id=brand_id)
        brand.promoted = True  # Mark as promoted
        brand.save()
        return JsonResponse({"message": "Brand promoted successfully!", "promoted": True})
    return JsonResponse({"error": "Invalid request method"}, status=400)


def view_promoted_brands(request):
    if request.method == 'GET':
        # Filter products where promoted is True
        promoted_brands = Brand.objects.filter(promoted=True)

        promoted_brands_list = [
            {
                "id": brand.id,
                "name": brand.name

            }
            for brand in promoted_brands
        ]

        return JsonResponse({"promoted_products": promoted_brands_list}, status=200)

    return JsonResponse({"error": "Invalid request method"}, status=400)


@csrf_exempt
def remove_promoted_brand(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)  # Parse the JSON request body
            brand_id = data.get('brand_id')  # Get the brand ID from the request
            brand = get_object_or_404(Brand, id=brand_id)  # Retrieve the brand

            if brand.promoted:  # Check if the brand is currently promoted
                brand.promoted = False  # Set promoted to False
                brand.save()  # Save the updated brand
                return JsonResponse({"message": "Brand removed from promoted successfully!", "promoted": False})
            else:
                return JsonResponse({"message": "Brand is not promoted.", "promoted": False})

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid request method"}, status=400)




def send_vendor_notification(vendor_id, message):
    # Send a message to the vendor's group
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f'vendor_{vendor_id}',  # Vendor group name
        {
            'type': 'vendor_notification',  # Event type
            'message': message,  # Notification message
        }
    )


@api_view(['POST'])
@permission_classes([IsAdminUser])
def add_subscriber(request):
    try:
        data = request.data
        email = data.get('email')
        address = data.get('address')
        service_type = data.get('service_type')
        plan = data.get('plan')
        duration = data.get('duration')
        start_date = data.get('start_date')
        assigned_vendor_ids = data.get('assigned_vendors', [])

        if not User.objects.filter(email=email).exists():
            return Response({'error': 'No such user registered.'}, status=400)

        if not start_date:
            return Response({'error': 'Start date is required.'}, status=400)
        try:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        except ValueError:
            return Response({'error': 'Invalid start_date format.'}, status=400)

        try:
            duration = int(duration)
        except (ValueError, TypeError):
            return Response({'error': 'Duration must be an integer.'}, status=400)

        if not address:
            return Response({'error': 'Address is required for geocoding.'}, status=400)

        subscriber_lat, subscriber_lon = get_geocoded_location(address)

        subscriber = Subscriber.objects.create(
            email=email,
            address=address,
            service_type=service_type,
            plan=plan,
            duration=duration,
            start_date=start_date,
            latitude=subscriber_lat,
            longitude=subscriber_lon,
        )

        vendors = Services.objects.filter(id__in=assigned_vendor_ids)
        subscriber.assigned_vendors.set(vendors)

        return Response({'message': 'Subscriber added successfully.', 'id': subscriber.id}, status=200)

    except Exception as e:
        return Response({'error': str(e)}, status=500)
    
    
@api_view(['GET'])
@permission_classes([IsAdminUser])
def view_subscribers(request):
    search_query = request.GET.get('search', '')
    if search_query:
        subscribers = Subscriber.objects.filter(email__icontains=search_query)
    else:
        subscribers = Subscriber.objects.all()

    data = [{
        "id": sub.id,
        "email": sub.email,
        "address": sub.address,
        "service_type": sub.service_type,
        "plan": sub.plan,
        "duration": sub.duration,
        "start_date": sub.start_date.strftime('%Y-%m-%d') if sub.start_date else None,
        "end_date": sub.end_date.strftime('%Y-%m-%d') if sub.end_date else None,
        "assigned_vendors": [vendor.vendor_name for vendor in sub.assigned_vendors.all()]
    } for sub in subscribers]

    return Response({"user": data}, status=200)

    
@csrf_exempt
@api_view(['GET'])
@permission_classes([IsAdminUser])
def view_users_by_admin(request):
    if request.method == 'GET':
        search_query = request.GET.get('search', '')
        if search_query:
            user = User.objects.filter(first_name__icontains=search_query)
        else:
            user = User.objects.filter(is_superuser=False)
        data = [{  "id": users.id,
                    "username": users.username,
                    "first_name": users.first_name,
                    "last_name": users.last_name,
                    "email": users.email} for users in user]
        return JsonResponse({"user": data}, safe=False)

@csrf_exempt
def admin_login(request):
    if request.method == 'POST':
        # Get the username and password from POST request
        username = request.POST.get('username')
        password = request.POST.get('password')

        # Authenticate user
        user = authenticate(username=username, password=password)

        # Check if user is admin (superuser)
        if user and user.is_superuser:
            refresh = RefreshToken.for_user(user)

            # Calculate expiration date for cookies
            expires_date = datetime.utcnow() + timedelta(days=30)

            # Prepare the response with access and refresh tokens
            response = JsonResponse({
                "message": "Admin login successful",
                "access_token": str(refresh.access_token),
                "refresh_token": str(refresh)
            })

            # Set cookies for access_token and refresh_token
            response.set_cookie(
                'access_token', str(refresh.access_token),
                max_age=60 * 60,  # 1 hour for access_token
                httponly=True,
                secure=True,  # True for production (HTTPS)
                samesite='None'  # Allows cross-origin cookies
            )
            response.set_cookie(
                'refresh_token', str(refresh),
                max_age=28 * 24 * 60 * 60,  # 28 days for refresh_token
                httponly=True,
                secure=True,  # True for production (HTTPS)
                samesite='None'  # Allows cross-origin cookies
            )

            return response

        # Invalid admin credentials
        return JsonResponse({"error": "Invalid admin credentials"}, status=401)

    # Method not allowed if not POST request
    return JsonResponse({"error": "Method not allowed"}, status=405)


@csrf_exempt
def Admin_Profile(request):
    if request.method == 'GET':
        # Retrieve the token from the cookies
        token = request.COOKIES.get('access_token')  # Get token from cookies

        if not token:
            return JsonResponse({"error": "Authorization token missing"}, status=400)

        try:
            # Decode the token to extract user_id
            access_token = AccessToken(token)  # Decode the token
            user_id = access_token['user_id']  # Extract user_id

            print(f"Extracted user_id from token: {user_id}")

            # Get the admin user's details using the extracted user_id
            user = User.objects.get(id=user_id)

            # Return the admin's profile details as JSON response
            return JsonResponse({
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'is_superuser': user.is_superuser,
                'date_joined': user.date_joined,
                'last_login': user.last_login,
            })

        except User.DoesNotExist:
            return JsonResponse({"error": "Admin not found"}, status=404)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid request method"}, status=405)


@csrf_exempt
def UserLogin(request):
    if request.method == 'POST':
        content_type = request.content_type
        print(f"Content-Type: {content_type}")
        print(f"Request Body: {request.body}")
        print(f"POST Data: {request.POST}")

        username = request.POST.get('username')
        password = request.POST.get('password')

        if not username or not password:
            return JsonResponse({"error": "Missing username or password"}, status=400)

        user = authenticate(username=username, password=password)

        if user and not user.is_superuser:
            refresh = RefreshToken.for_user(user)

            # Calculate expiration date for cookies
            expires_date = datetime.utcnow() + timedelta(days=30)

            response = JsonResponse({
                "message": "User login successful",
                "access_token": str(refresh.access_token),
                "refresh_token": str(refresh)
            })

            response.set_cookie(
                'access_token', str(refresh.access_token),
                max_age=30 * 24 * 60 * 60,
                httponly=True,
                secure= True,  # True for production (HTTPS)
                samesite='None' # Allow cross-origin cookies
            )
            response.set_cookie(
                'refresh_token', str(refresh),
                max_age=28 * 24 * 60 * 60,
                httponly=True,
                secure= True,  # True for production (HTTPS)
                samesite='None'
            )
            return response

        return JsonResponse({"error": "Invalid user credentials"}, status=401)

    return JsonResponse({"error": "Invalid request method"}, status=405)


@csrf_exempt
def RefreshAccessToken(request):
    refresh_token = request.COOKIES.get('refresh_token')

    if not refresh_token:
        return JsonResponse({"error": "Refresh token is missing"}, status=400)

    try:
        # Decode and verify the refresh token
        refresh = RefreshToken(refresh_token)

        # Generate a new access token
        new_access_token = str(refresh.access_token)

        # Return the new access token
        return JsonResponse({"access_token": new_access_token})

    except TokenError as e:
        return JsonResponse({"error": str(e)}, status=401)
    
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_logged_in_user(request):
    # Retrieve the token from the cookies
    token = request.COOKIES.get(settings.SIMPLE_JWT['AUTH_COOKIE'])

    if not token:
        raise AuthenticationFailed('Authentication token not found in cookies')

    try:
        # Decode the token to get the payload
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get('user_id')

        if not user_id:
            raise AuthenticationFailed('User ID not found in token')

        # Fetch the user from the database
        user = User.objects.get(id=user_id)

        # Prepare user details
        user_details = {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            # Add any other fields you need
        }

        return Response(user_details)

    except jwt.ExpiredSignatureError:
        raise AuthenticationFailed('Token has expired')
    except jwt.DecodeError:
        raise AuthenticationFailed('Error decoding token')
    except User.DoesNotExist:
        raise AuthenticationFailed('User not found')

from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.models import User

@csrf_exempt
def Vendor_Login(request):
    if request.method == 'POST':
        phone_number = request.POST.get('phone_number')
        password = request.POST.get('password')

        # Debug: Print received data
        print(f"Login attempt - Phone: {phone_number}, Password provided: {'Yes' if password else 'No'}")

        if not phone_number or not password:
            return JsonResponse({"error": "Phone number and password are required"}, status=400)

        try:
            # Retrieve vendor using phone number
            vendor = Services.objects.get(phone_number=phone_number)
            print(f"Vendor found: {vendor.vendor_name}")

            # FIXED: Use check_password for hashed passwords
            if check_password(password, vendor.password):
                print("Password verification successful")
                
                # Create custom token for the vendor
                refresh = RefreshToken()
                refresh['vendor_id'] = vendor.id  # Store vendor-specific info in the token

                response = JsonResponse({
                    "message": "Vendor login successful",
                    "access_token": str(refresh.access_token),
                    "refresh_token": str(refresh),
                    "vendor_id": vendor.id  # Include vendor_id in response for debugging
                })
                
                # Set tokens in secure cookies
                response.set_cookie(
                    'access_token', str(refresh.access_token),
                    max_age=30 * 24 * 60 * 60,
                    httponly=True,
                    secure=True,  # True for production (HTTPS)
                    samesite='None'  # Allow cross-origin cookies
                )
                response.set_cookie(
                    'refresh_token', str(refresh),
                    max_age=30 * 24 * 60 * 60,
                    httponly=True,
                    secure=True,  # True for production (HTTPS)
                    samesite='None'
                )
                return response
            else:
                print("Password verification failed")
                return JsonResponse({"error": "Invalid credentials"}, status=401)

        except Services.DoesNotExist:
            print(f"Vendor not found with phone number: {phone_number}")
            return JsonResponse({"error": "Invalid credentials"}, status=401)
        except Exception as e:
            print(f"Login error: {str(e)}")
            return JsonResponse({"error": "Login failed"}, status=500)

    return JsonResponse({"error": "Invalid request method"}, status=405)



@csrf_exempt
def Vendor_Profile(request):
    if request.method == 'GET':
        # Retrieve the token from the cookies
        token = request.COOKIES.get('access_token')

        if not token:
            return JsonResponse({"error": "Authorization token missing"}, status=400)

        try:
            # Decode the token to extract vendor_id
            access_token = AccessToken(token)
            vendor_id = access_token.get('vendor_id')  # Use .get() for safer access

            if not vendor_id:
                return JsonResponse({"error": "Invalid token: vendor_id not found"}, status=400)

            print(f"Extracted vendor_id from token: {vendor_id}")

            # Get the vendor's details using the extracted vendor_id
            vendor = Services.objects.get(id=vendor_id)

            # Return the vendor's profile details as JSON response
            return JsonResponse({
                'id': vendor.id,
                'vendor_name': vendor.vendor_name,
                'phone_number': vendor.phone_number,
                'whatsapp_number': vendor.whatsapp_number,
                'email': vendor.email,
                'address': vendor.address,
                'latitude': vendor.latitude,
                'longitude': vendor.longitude,
                'service_category': vendor.service_category.name if vendor.service_category else None,
                'service_details': vendor.service_details,
                'rate': vendor.rate,
                "images": [img.image.url if hasattr(img.image, 'url') else img.image for img in vendor.images.all()], 
                'created_at': vendor.created_at,
                'updated_at': vendor.updated_at
            })

        except Services.DoesNotExist:
            return JsonResponse({"error": "Vendor not found"}, status=404)
        except Exception as e:
            print(f"Profile error: {str(e)}")
            return JsonResponse({"error": "Failed to retrieve profile"}, status=500)

    return JsonResponse({"error": "Invalid request method"}, status=405)



@csrf_exempt
def Logout(request):
    if request.method == 'POST':
        try:
            refresh_token = request.COOKIES.get('refresh_token')
            if refresh_token:
                token = OutstandingToken(refresh_token)
                BlacklistedToken.objects.create(token=token)  # Blacklist the token
        except Exception as e:
            pass  # Log the exception if needed

        response = JsonResponse({"message": "Logout successful"})
        response.delete_cookie('access_token', samesite='None')
        response.delete_cookie('refresh_token', samesite='None')
        return response

    return JsonResponse({"error": "Invalid request method"}, status=405)


@csrf_exempt
@api_view(['POST'])
@authentication_classes([CustomJWTAuthentication])
@permission_classes([IsAuthenticated])
def add_address(request):
    try:
        data = json.loads(request.body)
        name = data.get('name')
        if not name:
            return JsonResponse({'error': 'Name is required'}, status=400)

        phone_number = data.get('phone_number')
        if not phone_number:
            return JsonResponse({'error': 'Phone number is required'}, status=400)

        address = Address.objects.create(
            user=request.user,
            name=name,
            phone_number=phone_number,
            street=data.get('street'),
            building_name=data.get('building_name'),
            floor_apartment_no=data.get('floor_apartment_no'),
            landmark=data.get('landmark'),
            city=data.get('city'),
            area_district=data.get('area_district'),
            country=data.get('country', "United Arab Emirates"),
            address_type=data.get('address_type', "Home"),
            is_default=data.get('is_default', False),
        )

        return JsonResponse({'message': 'Address added successfully', 'address_id': address.id}, status=200)

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@api_view(['GET'])
@authentication_classes([CustomJWTAuthentication, ])
@permission_classes([IsAuthenticated])
def view_addresses(request):
    if request.method == 'GET':
        try:
            # Retrieve addresses with some optional filtering or ordering
            addresses = Address.objects.filter(user=request.user).order_by('-is_default', '-id')
            
            address_list = [{

                'id': address.id,
                'name' : address.name,
                'phone_number': address.phone_number,
                'street': address.street,
                'building_name': address.building_name,
                'floor_apartment_no': address.floor_apartment_no,
                'landmark': address.landmark,
                'city': address.city,
                'area_district': address.area_district,
                'country': address.country,
                'address_type': address.address_type,
                'is_default': address.is_default,


            } for address in addresses]
            
            return JsonResponse({
                'addresses': address_list,
                'total_count': len(address_list)
            }, status=200)
        
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Invalid request method'}, status=405)



@csrf_exempt
@api_view(['PUT'])
@authentication_classes([CustomJWTAuthentication])
@permission_classes([IsAuthenticated])
def set_default_address(request, address_id):
    try:
        # Get the address by ID from the URL
        address = Address.objects.get(id=address_id, user=request.user)
    except Address.DoesNotExist:
        return JsonResponse({'error': 'Address not found'}, status=404)

    # Set the selected address as default
    Address.objects.filter(user=request.user).update(is_default=False)  # Unset other addresses
    address.is_default = True
    address.save()
    return JsonResponse({'message': 'Default address set successfully'}, status=200)


@csrf_exempt
@api_view(['DELETE'])
@authentication_classes([CustomJWTAuthentication])
@permission_classes([IsAuthenticated])
def delete_address(request, address_id):
    try:
        # Get the address by ID from the URL
        address = Address.objects.get(id=address_id, user=request.user)
    except Address.DoesNotExist:
        return JsonResponse({'error': 'Address not found'}, status=404)

    # Delete the address
    address.delete()

    return JsonResponse({'message': 'Address deleted successfully'}, status=200)


#  Shipping address selection
@csrf_exempt
@api_view(['GET'])
@authentication_classes([CustomJWTAuthentication])
@permission_classes([IsAuthenticated])
def shipping_address(request):
    if request.method == 'GET':
        # Fetch all addresses for the logged-in user
        addresses = Address.objects.filter(user=request.user)

        address_list = []
        for address in addresses:
            address_list.append({
    'id': address.id,
    'name': address.name,
    'phone_number': address.phone_number,
    'street': address.street,
    'building_name': address.building_name,
    'floor_apartment_no': address.floor_apartment_no,
    'landmark': address.landmark,
    'city': address.city,
    'area_district': address.area_district,
    'country': address.country,
    'address_type': address.address_type,
    'is_default': address.is_default,
}
)

        return JsonResponse({'addresses': address_list})
    #

    elif request.method == 'POST':
        try:
            data = json.loads(request.body)  # Get the selected address ID from the request
            address_id = data.get('address_id')

            # Try to fetch the selected address for shipping
            selected_address = Address.objects.get(id=address_id, user=request.user)

            # Process the selected address (e.g., store with the order)
            return JsonResponse({'message': 'Address selected for shipping', 'address_id': selected_address.id},
                                status=200)

        except Address.DoesNotExist:
            return JsonResponse({'error': 'Address not found'}, status=404)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON data'}, status=400)

    return JsonResponse({'error': 'Only POST or GET methods are allowed'}, status=405)

# # 1. Add address view
# @api_view(['POST'])
# @authentication_classes([JWTAuthentication])
# @permission_classes([IsAuthenticated])
# @csrf_exempt  # Use @csrf_exempt if you're sending requests from React
# def add_address(request):
#     if request.method == 'POST':
#         try:
#             data = json.loads(request.body)  # Parse the incoming JSON data
#             street = data.get('street')
#             city = data.get('city')
#             state = data.get('state')
#             zip_code = data.get('zip_code')
#             country = data.get('country')
#             is_default = data.get('is_default', False)  # Default to False if not provided

#             # Create a new address
#             address = Address.objects.create(
#                 user=request.user,
#                 street=street,
#                 city=city,
#                 state=state,
#                 zip_code=zip_code,
#                 country=country,
#                 is_default=is_default
#             )

#             return JsonResponse({'message': 'Address added successfully', 'address_id': address.id}, status=200)

#         except json.JSONDecodeError:
#             return JsonResponse({'error': 'Invalid JSON data'}, status=400)

#     return JsonResponse({'error': 'Only POST method is allowed'}, status=405)


# @login_required
# @csrf_exempt
# def view_addresses(request):
#     if request.method == 'GET':
#         addresses = Address.objects.filter(user=request.user)

#         address_list = []
#         for address in addresses:
#             address_list.append({
#                 'id': address.id,
#                 'street': address.street,
#                 'city': address.city,
#                 'state': address.state,
#                 'zip_code': address.zip_code,
#                 'country': address.country,
#                 'is_default': address.is_default,
#             })

#         return JsonResponse({'addresses': address_list})
#     else:
#         return JsonResponse({'Error':'Invalid request method'})


# @login_required
# @csrf_exempt
# def set_default_address(request, address_id):
#     try:
#         # Get the address by ID from the URL
#         address = Address.objects.get(id=address_id, user=request.user)
#     except Address.DoesNotExist:
#         return JsonResponse({'error': 'Address not found'}, status=404)

#     # Set the selected address as default
#     Address.objects.filter(user=request.user).update(is_default=False)  # Unset other addresses
#     address.is_default = True
#     address.save()

#     return JsonResponse({'message': 'Default address set successfully'}, status=200)


# # 4. Shipping address selection
# @login_required
# @csrf_exempt
# def shipping_address(request):
#     if request.method == 'GET':
#         # Fetch all addresses for the logged-in user
#         addresses = Address.objects.filter(user=request.user)

#         address_list = []
#         for address in addresses:
#             address_list.append({
#                 'id': address.id,
#                 'street': address.street,
#                 'city': address.city,
#                 'state': address.state,
#                 'zip_code': address.zip_code,
#                 'country': address.country,
#                 'is_default': address.is_default,
#             })

#         return JsonResponse({'addresses': address_list})

#     elif request.method == 'POST':
#         try:
#             data = json.loads(request.body)  # Get the selected address ID from the request
#             address_id = data.get('address_id')

#             # Try to fetch the selected address for shipping
#             selected_address = Address.objects.get(id=address_id, user=request.user)

#             # Process the selected address (e.g., store with the order)
#             return JsonResponse({'message': 'Address selected for shipping', 'address_id': selected_address.id},
#                                 status=200)

#         except Address.DoesNotExist:
#             return JsonResponse({'error': 'Address not found'}, status=404)
#         except json.JSONDecodeError:
#             return JsonResponse({'error': 'Invalid JSON data'}, status=400)

#     return JsonResponse({'error': 'Only POST or GET methods are allowed'}, status=405)







@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAdminUser])
def add_service_category(request):
    if request.method == 'POST':
        try:
            # Parse JSON data from the request body
            data = json.loads(request.body)

            # Extract the category name
            name = data.get('name')

            # Validate the category name
            if not name:
                return JsonResponse({"error": "The 'name' field is required."}, status=400)

            # Check if the category already exists
            if ServiceCategory.objects.filter(name=name).exists():
                return JsonResponse({"error": "Service category already exists."}, status=400)

            # Create the new service category
            category = ServiceCategory.objects.create(name=name)

            return JsonResponse({
                "message": "Service category added successfully.",
                "service_category": {
                    "id": category.id,
                    "name": category.name
                }
            }, status=201)

        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON data."}, status=400)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid HTTP method."}, status=405)


def view_service_categories_user(request):
    try:
        # Retrieve all service categories from the database
        categories = ServiceCategory.objects.all()

        # Prepare the list of categories to return as JSON
        categories_data = []
        for category in categories:
            categories_data.append({
                "id": category.id,
                "name": category.name
            })

        # Return the categories data as JSON
        return JsonResponse({"service_categories": categories_data}, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

from django.db.models import Q

@csrf_exempt
def view_service_user(request):
    try:
        user_lat = float(request.GET.get('lat')) if request.GET.get('lat') else None
        user_lng = float(request.GET.get('lng')) if request.GET.get('lng') else None
    except (TypeError, ValueError):
        return JsonResponse({"error": "Invalid Latitude or Longitude."}, status=400)

    radius = 20
    nearby_services = []

    search_query = request.GET.get('service', "").strip()
    services = Services.objects.all()

    # 🔍 Apply search filter on vendor_name or address
    if search_query:
        services = services.filter(
            Q(address__icontains=search_query) |
            Q(vendor_name__icontains=search_query)
        )

    def get_service_data(service, distance=None):
        ratings = service.ratings.all()
        avg_rating = round(sum(r.rating for r in ratings) / ratings.count(), 1) if ratings.exists() else 0
        return {
            "id": service.id,
            "vendor_name": service.vendor_name,
            "phone_number": service.phone_number,
            "whatsapp_number": service.whatsapp_number,
            "service_category": service.service_category.name if service.service_category else None,
            "service_details": service.service_details,
            "address": service.address,
            "rate": service.rate,
            "images": [image.image.url for image in service.images.all()],
            "average_rating": avg_rating,
            "total_reviews": ratings.count(),
            **({"distance": round(distance, 2)} if distance is not None else {})
        }

    if user_lat is not None and user_lng is not None:
        for service in services:
            if service.latitude is not None and service.longitude is not None:
                distance = haversine(user_lat, user_lng, service.latitude, service.longitude)
                if distance <= radius:
                    nearby_services.append(get_service_data(service, distance))

    if not user_lat or not user_lng or not nearby_services:
        for service in services:
            nearby_services.append(get_service_data(service))

    return JsonResponse({'services': nearby_services}, status=200)


@csrf_exempt
def view_single_service_user(request, service_id):
    try:
        # Retrieve the service with the given service_id
        service = Services.objects.get(id=service_id)

        # Prepare the service data to return as JSON
        service_data = {
            "id": service.id,
            "vendor_name": service.vendor_name,
            "phone_number": service.phone_number,
            "whatsapp_number": service.whatsapp_number,
            "service_category": service.service_category.name if service.service_category else None,
            "service_details": service.service_details,
            "address": service.address,
            "rate": service.rate,
            "images": [image.image.url for image in service.images.all()]
        }

        # Return the service data as JSON
        return JsonResponse({"service": service_data}, status=200)

    except Services.DoesNotExist:
        return JsonResponse({"error": "Service not found."}, status=404)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


from django.utils.timezone import localtime
class LogServiceInteractionView(APIView):
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            # Retrieve action and service_id from request
            action = request.data.get('action')  # DRF uses `request.data` for POST
            service_id = request.data.get('service_id')

            # Get the current authenticated user
            user = request.user  # DRF ensures this is populated

            if action and service_id:
                service = Services.objects.get(id=service_id)

                # Log the interaction
                if action in ['CALL', 'WHATSAPP']:
                    log = ServiceInteractionLog(
                        service=service,
                        action=action,
                        user=user
                    )
                    log.save()
                    # Send email after log is saved
                    self.send_log_email(log)

                    log_timestamp_local = localtime(log.timestamp).strftime('%Y-%m-%d %H:%M:%S')
                    user_details = {
                        "username": user.username,
                        "full_name": user.get_full_name(),
                        "email": user.email
                    }

                    return Response({
                        "message": f"Interaction logged successfully for {action}.",
                        "timestamp": log_timestamp_local,
                        "user": user_details
                    }, status=201)

                return Response({"error": "Invalid action."}, status=400)
            else:
                return Response({"error": "Missing required parameters."}, status=400)

        except Services.DoesNotExist:
            return Response({"error": "Service not found."}, status=404)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    def send_log_email(self, log):
        """Send an email notification when a log is created."""
        try:
            timestamp = localtime(log.timestamp).strftime('%Y-%m-%d %H:%M:%S')
            user_full_name = log.user.get_full_name() if log.user else "Anonymous"

            subject = f"Service Interaction Log for {log.service.vendor_name}"
            message = f"""
            Dear {log.service.vendor_name},

            A new interaction log has been recorded for your service. Here are the details:

            Service: {log.service.vendor_name}
            Action: {log.action}
            Timestamp: {timestamp}
            User: {log.user.username if log.user else 'Anonymous'}
            Full Name: {user_full_name}

            Thank you,
            Handcar Team
            """

            recipient_list = [log.service.email]  # Ensure this field exists in your model

            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=recipient_list,
            )
        except Exception as e:
            print(f"Error sending email: {str(e)}")  # Log error


def vendor_service_requests(request):
    if request.method == "GET":
        service_id = request.GET.get("service_id")  # Get service_id from query params

        if not service_id:
            return JsonResponse({"error": "Service ID is required."}, status=400)

        try:
            service = Services.objects.get(id=service_id)  # Fetch the specific service

            logs = ServiceInteractionLog.objects.filter(service=service, status="PENDING")  # Filter logs

            data = [{
                "id": log.id,
                "service": log.service.vendor_name,
                "action": log.action,
                "timestamp": localtime(log.timestamp).strftime('%Y-%m-%d %H:%M:%S'),
                "user": log.user.username if log.user else "Anonymous",
                "status": log.status
            } for log in logs]

            return JsonResponse({"requests": data}, status=200)

        except Services.DoesNotExist:
            return JsonResponse({"error": "Service not found."}, status=404)

    return JsonResponse({"error": "Invalid request method."}, status=405)


class UpdateServiceRequestStatusView(APIView):
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        log_id = request.data.get("log_id")
        status = request.data.get("status")  # Should be 'ACCEPTED' or 'DECLINED'

        if status not in ['ACCEPTED', 'DECLINED']:
            return Response({"error": "Invalid status"}, status=400)

        try:
            log = ServiceInteractionLog.objects.get(id=log_id, service__vendor=request.user)
            log.status = status
            log.save()

            return Response({"message": f"Request {status.lower()} successfully!"}, status=200)

        except ServiceInteractionLog.DoesNotExist:
            return Response({"error": "Request not found or unauthorized"}, status=404)



# from django.shortcuts import render
# from django.core.mail import send_mail
# from django.http import HttpResponse
# from .models import ServiceInteractionLog
# @csrf_exempt
# def send_log_email_view(request):
#     if request.method == 'POST':
#         try:
#             log_id = request.POST.get('log_id')
#             log = ServiceInteractionLog.objects.get(id=log_id)
#
#             # Format the timestamp to a readable format
#             timestamp = localtime(log.timestamp).strftime('%Y-%m-%d %H:%M:%S')
#             user_full_name = log.user.get_full_name() if log.user else "Anonymous"
#             # user_username = log.user.username if log.user else "Anonymous"
#
#             # Construct the email subject and message
#             subject = f"Service Interaction Log for {log.service.vendor_name}"
#             message = f"""
#             Dear {log.service.vendor_name},
#
#             A new interaction log has been recorded for your service. Here are the details:
#
#             Service: {log.service.vendor_name}
#             Action: {log.action}
#             Timestamp: {timestamp}
#             User: {log.user.username if log.user else 'Anonymous'}
#             Full Name: {user_full_name}
#
#             Thank you,
#             Handcar Team
#             """
#
#             # Recipient email
#             recipient_list = [log.service.email]  # Replace with the actual service email field
#
#             # Send the email
#             send_mail(
#                 subject=subject,
#                 message=message,
#                 from_email=settings.DEFAULT_FROM_EMAIL,
#                 recipient_list=recipient_list,
#             )
#
#             return JsonResponse({"message": "Log email sent successfully!"}, status=200)
#         except ServiceInteractionLog.DoesNotExist:
#             return JsonResponse({"error": "Log not found."}, status=404)
#         except Exception as e:
#             return JsonResponse({"error": f"Error sending email: {str(e)}"}, status=500)
#
#     return JsonResponse({"error": "Invalid request method."}, status=405)


@csrf_exempt
@api_view(["GET"])  # Required for permission_classes to work
@permission_classes([IsAdminUser])
def get_service_interaction_logs_admin(request):
    try:
        # Get query parameters
        service_name = request.GET.get('service_name')
        mode_of_communication = request.GET.get('mode_of_communication')  # e.g., "CALL", "WHATSAPP"

        # Base queryset
        logs = ServiceInteractionLog.objects.select_related('service')

        # Apply filters if query parameters are provided
        if service_name:
            logs = logs.filter(
                service__vendor_name__icontains=service_name
            ).exclude(service__vendor_name__isnull=True).exclude(service__vendor_name__exact="")

        if mode_of_communication:
            logs = logs.filter(action=mode_of_communication)  # Match against choices in ACTION_CHOICES

        # Prepare data for response
        logs_data = [
            {
                "id": log.id,
                "service_name": log.service.vendor_name,
                "action": log.get_action_display(),  # Use display value for choices
                "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "user_id": log.user_id,
                "user_name": log.user.get_full_name() if log.user and log.user.get_full_name() else (log.user.username if log.user else "Unknown User")
            }
            for log in logs
        ]

        return JsonResponse({"logs": logs_data}, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@api_view(['POST'])
@authentication_classes([CustomJWTAuthentication])
@permission_classes([IsAuthenticated])
def add_service_rating(request):
    try:
        # Parse the JSON request body
        data = json.loads(request.body)

        # Extract required fields
        service_id = data.get('service_id')
        rating_value = data.get('rating')
        comment = data.get('comment', '')  # Optional

        # Validate the input
        if not service_id or not rating_value:
            return JsonResponse({"error": "service_id and rating are required."}, status=400)

        if int(rating_value) < 1 or int(rating_value) > 5:
            return JsonResponse({"error": "Rating must be between 1 and 5."}, status=400)

        # Fetch the related service object
        try:
            service = Services.objects.get(id=service_id)
        except Services.DoesNotExist:
            return JsonResponse({"error": "Service not found."}, status=404)

        # Use the authenticated user from the request
        user = request.user

        # Check if the user has already rated the service (optional logic)
        existing_rating = Service_Rating.objects.filter(service=service, user=user).first()
        if existing_rating:
            return JsonResponse({"error": "You have already rated this service."}, status=400)

        # Create the new rating
        new_rating = Service_Rating(service=service, user=user, rating=rating_value, comment=comment)
        new_rating.save()

        return JsonResponse({"message": "Rating added successfully."}, status=201)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)



@csrf_exempt
def view_service_rating(request):
    try:
        # Get the service ID from the query parameters
        service_id = request.GET.get('service_id')

        if not service_id:
            # If no service_id is provided, return an error response
            return JsonResponse({"error": "Service ID is required."}, status=400)

        # Filter ratings by the provided service ID
        service_ratings = Service_Rating.objects.filter(service_id=service_id)

        # Check if there are any ratings for the given service ID
        if not service_ratings.exists():
            return JsonResponse({"message": "No ratings found for the specified service."}, status=404)

        # Initialize an empty list to store rating data
        ratings_data = []

        # Iterate through each rating and collect the data
        for rating in service_ratings:
            rating_data = {
                "id": rating.id,
                "vendor_name": rating.service.vendor_name,
                "username": rating.user.first_name,
                "rating": rating.rating,
                "comment": rating.comment,
            }
            ratings_data.append(rating_data)  # Append each rating to the list

        # Return the ratings data as JSON
        return JsonResponse({"Ratings": ratings_data}, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
def get_nearby_services(request):
    try:
        user_lat = float(request.GET.get('lat'))  # User's latitude
        user_lng = float(request.GET.get('lng'))  # User's longitude
    except (TypeError, ValueError):
        return JsonResponse({"error": "Invalid Latitude or Longitude."}, status=400)

    radius = 20  # Define the search radius in kilometers

    nearby_services = []

    # Loop through all services and check if they are within the radius
    for service in Services.objects.all():
        # Ensure service has valid latitude and longitude before calculating distance
        if service.latitude is not None and service.longitude is not None:
            # Calculate the distance only if both latitude and longitude are available
            distance = haversine(user_lat, user_lng, service.latitude, service.longitude)

            if distance <= radius:
                nearby_services.append({
                    'name': service.vendor_name,
                    'latitude': service.latitude,
                    'longitude': service.longitude,
                    'distance': round(distance, 2)  # Include the distance
                })

    return JsonResponse({'services': nearby_services}, status=200)


class Edit_UserProfile_By_user(APIView):
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            user = request.user  # DRF automatically adds the authenticated user
            data = request.data  # DRF parses JSON body for you

            # Optional fields the user can edit
            first_name = data.get('first_name')
            last_name = data.get('last_name')
            email = data.get('email')

            if first_name:
                user.first_name = first_name
            if last_name:
                user.last_name = last_name
            if email:
                # Add email validation if needed
                user.email = email

            user.save()

            return Response({
                "message": "User details updated successfully",
                "user": {
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.email,
                }
            }, status=200)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

#
#
# @csrf_exempt
# def add_vendor_by_admin(request):
#     if request.method == 'POST':
#         try:
#             # Parse JSON data from the request body
#             data = json.loads(request.body)
#
#             vendor_name = data.get('vendor_name')
#             phone_number = data.get('phone_number')
#             email = data.get('email')
#             password = data.get('password')
#
#             # Validate required fields
#             if not vendor_name or not phone_number or not email or not password:
#                 return JsonResponse({"error": "All fields are required."}, status=400)
#
#             # Validate email format
#             try:
#                 validate_email(email)
#             except ValidationError:
#                 return JsonResponse({"error": "Invalid email format."}, status=400)
#
#             # Check if email already exists
#             if Services.objects.filter(email=email).exists():
#                 return JsonResponse({"error": "Email already exists."}, status=400)
#
#             # Create the vendor
#             vendor = Services.objects.create(
#                 vendor_name=vendor_name,
#                 phone_number=phone_number,
#                 email=email,
#                 password=password
#             )
#
#             return JsonResponse({
#                 "message": "Service Vendor added successfully.",
#                 "Service": {
#                     "id": vendor.id,
#                     "vendor_name": vendor.vendor_name,
#                     "phone_number": vendor.phone_number,
#                     "email": vendor.email,
#                 }
#             }, status=201)
#
#         except json.JSONDecodeError:
#             return JsonResponse({"error": "Invalid JSON data."}, status=400)
#         except Exception as e:
#             return JsonResponse({"error": str(e)}, status=500)
#
#     return JsonResponse({"error": "Invalid HTTP method."}, status=405)
#


@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAdminUser])  # Ensure only admin can access this view
def add_vendor_by_admin(request):
    if request.method == 'POST':
        try:
            # Parse JSON data from the request body
            data = json.loads(request.body)

            vendor_name = data.get('vendor_name')
            phone_number = data.get('phone_number')
            email = data.get('email')
            password = data.get('password')

            # Validate required fields
            if not vendor_name or not phone_number or not email or not password:
                return JsonResponse({"error": "All fields are required."}, status=400)

            # Validate email format
            try:
                validate_email(email)
            except ValidationError:
                return JsonResponse({"error": "Invalid email format."}, status=400)

            # Check if email already exists
            if Services.objects.filter(email=email).exists():
                return JsonResponse({"error": "Email already exists."}, status=400)

            # Check if phone number already exists
            if Services.objects.filter(phone_number=phone_number).exists():
                return JsonResponse({"error": "Phone number already exists."}, status=400)

            # Create the vendor with hashed password
            vendor = Services.objects.create(
                vendor_name=vendor_name,
                phone_number=phone_number,
                email=email,
                password=make_password(password)  # This is correct - password is hashed
            )

            return JsonResponse({
                "message": "Service Vendor added successfully.",
                "Service": {
                    "id": vendor.id,
                    "vendor_name": vendor.vendor_name,
                    "phone_number": vendor.phone_number,
                    "email": vendor.email,
                }
            }, status=201)

        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON data."}, status=400)
        except Exception as e:
            print(f"Add vendor error: {str(e)}")
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid HTTP method."}, status=405)


@csrf_exempt
@api_view(['GET'])
@permission_classes([IsAdminUser])
def view_services_by_admin(request):
    if request.method == 'GET':
        search_query = request.GET.get('search', '').strip()
        print("Search Query:", search_query)  # Debugging
        if search_query:
            vendors = Services.objects.filter(vendor_name__icontains=search_query)
        else:
            vendors = Services.objects.all()
        data = [{"id": vendor.id,
                 "name": vendor.vendor_name,
                 "phone number": vendor.phone_number,
                 "email": vendor.email,
                 "location": vendor.address, 
                 "Joined at": vendor.created_at.strftime("%Y-%m-%d %H:%M:%S")} for vendor in vendors]
        return JsonResponse({"vendor": data}, safe=False)

@csrf_exempt
def edit_vendor_profile(request, vendor_id):
    if request.method == 'GET':
        try:
            # Retrieve the vendor
            vendor = get_object_or_404(Services, id=vendor_id)

            # Return vendor data as JSON
            vendor_data = {
                "vendor_name": vendor.vendor_name,
                "email": vendor.email,
                "phone_number": vendor.phone_number,
                "whatsapp_number": vendor.whatsapp_number,
                "address": vendor.address,
                "latitude": vendor.latitude,
                "longitude": vendor.longitude,
                "service_category": vendor.service_category.name,
                "service_details": vendor.service_details,
                "rate": vendor.rate,
                "images": [image.image.url for image in vendor.images.all()]
            }
            return JsonResponse(vendor_data, status=200)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    elif request.method == 'POST':
        try:
            # Retrieve the vendor to be edited
            vendor = get_object_or_404(Services, id=vendor_id)

            # Parse JSON data
            data = request.POST

            # Update fields if provided
            vendor.vendor_name = data.get('vendor_name', vendor.vendor_name)  # Vendor can edit name
            vendor.email = data.get('email', vendor.email)  # Vendor can edit email
            vendor.phone_number = data.get('phone_number', vendor.phone_number)  # Vendor can edit phone number

            # Vendor-specific fields that only vendors can update
            vendor.whatsapp_number = data.get('whatsapp_number', vendor.whatsapp_number)
            # vendor.address = data.get('address', vendor.address)
            new_address = data.get('address')
            if new_address and new_address != vendor.address:
                vendor.address = new_address
                print(f"New address set: {new_address}")
                vendor.latitude, vendor.longitude = geocode_address(new_address)
                print(f"Geocoded latitude: {vendor.latitude}, longitude: {vendor.longitude}")
            vendor.service_details = data.get('service_details', vendor.service_details)
            vendor.rate = data.get('rate', vendor.rate)
            service_category_name = data.get('service_category')
            if service_category_name:
                service_category = ServiceCategory.objects.filter(name=service_category_name).first()
                if service_category:
                    vendor.service_category = service_category
                else:
                    return JsonResponse({"error": "Invalid service category name."}, status=400)
            vendor.save()

            if 'images' in request.FILES:
                uploaded_images = request.FILES.getlist('images')  # Get the uploaded files
                for image in uploaded_images:
                    # Upload each image to Cloudinary
                    cloudinary_response = upload(image)
                    image_url = cloudinary_response['secure_url']  # Get the secure URL from the response

                    # Save the image URL in the ServiceImage model
                    ServiceImage.objects.create(service=vendor, image=image_url)
            return JsonResponse({"message": "Vendor updated successfully."}, status=200)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid HTTP method."}, status=405)

@csrf_exempt
@api_view(['DELETE'])
@permission_classes([IsAdminUser])
def delete_service_by_admin(request, service_id):
    if request.method == 'DELETE':
        try:
            # Retrieve the service by ID
            service = get_object_or_404(Services, id=service_id)
            # service = Services.objects.get(id=service_id)

            # Delete the service
            service.delete()

            return JsonResponse({"message": "Service deleted successfully."}, status=200)

        except Services.DoesNotExist:
            return JsonResponse({"error": "Service not found."}, status=404)
        except Exception as e:
            print(f"Error: {e}")
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid HTTP method."}, status=405)



@csrf_exempt
@api_view(['GET'])
@permission_classes([IsAdminUser])
def view_service_category(request):
    try:
        # Retrieve all categories
        categories = ServiceCategory.objects.all()

        # Prepare data for all categories
        categories_data = [
            {
                "id": category.id,
                "name": category.name
            }
            for category in categories
        ]

        # Return the list of categories
        return JsonResponse({"categories": categories_data}, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)



@csrf_exempt
@permission_classes([IsAdminUser])
def edit_service_category(request, service_category_id):
    if request.method == 'GET':
        try:
            # Retrieve the category by ID
            category = ServiceCategory.objects.get(id=service_category_id)

            # Return category details
            return JsonResponse({
                "id": category.id,
                "name": category.name
            }, status=200)

        except ServiceCategory.DoesNotExist:
            return JsonResponse({"error": "Service category not found."}, status=404)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    elif request.method == 'POST':
        try:
            # Parse JSON data from the request body
            data = json.loads(request.body)

            # Extract the new name
            new_name = data.get('name')

            if not new_name:
                return JsonResponse({"error": "The 'name' field is required."}, status=400)

            # Check if the category exists
            try:
                category = ServiceCategory.objects.get(id=service_category_id)
            except ServiceCategory.DoesNotExist:
                return JsonResponse({"error": "Service category not found."}, status=404)

            # Update the category name
            category.name = new_name
            category.save()

            return JsonResponse({
                "message": "Service category updated successfully.",
                "service_category": {
                    "id": category.id,
                    "name": category.name
                }
            }, status=200)

        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON data."}, status=400)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    else:
        return JsonResponse({"error": "Invalid HTTP method. Use GET for retrieving and POST for updating."}, status=405)




@csrf_exempt
@api_view(['DELETE'])
@permission_classes([IsAdminUser])
def delete_service_category(request, service_category_id):
    if request.method == 'DELETE':
        try:
            # Retrieve the category by ID
            category = ServiceCategory.objects.get(id=service_category_id)

            # Delete the category
            category.delete()

            return JsonResponse({"message": "Service category deleted successfully."}, status=200)

        except ServiceCategory.DoesNotExist:
            return JsonResponse({"error": "Service category not found."}, status=404)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid HTTP method. Use DELETE for removing."}, status=405)




@csrf_exempt
def forgot_password(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email')

            if not email:
                return JsonResponse({"error": "Email is required."}, status=400)

            # Fetch user by email
            User = get_user_model()
            user = User.objects.filter(email=email).first()
            if not user:
                return JsonResponse({"error": "No user found with this email."}, status=404)

            # Generate password reset token and UID
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))

            # Construct reset URL
            reset_url = f"{settings.SITE_URL}/reset-password/{uid}/{token}"

            # Prepare email
            subject = "Password Reset Requested"
            message = f"""
Hi {user.username},

You requested a password reset. To reset your password, click the link below:

{reset_url}

If you didn't request this, you can ignore this email.

Regards,  
Team Handcar
"""

            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email])

            return JsonResponse({"message": "Password reset email sent."}, status=200)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid request method."}, status=405)

@csrf_exempt
def reset_password(request, uidb64, token):
    try:
        # Decode the UID and get user
        uid = urlsafe_base64_decode(uidb64).decode()
        User = get_user_model()
        user = User.objects.get(pk=uid)

        # Verify token
        if not default_token_generator.check_token(user, token):
            return JsonResponse({"error": "Invalid or expired token."}, status=400)

        if request.method == 'POST':
            data = json.loads(request.body)
            new_password = data.get('new_password')

            if not new_password:
                return JsonResponse({"error": "New password is required."}, status=400)

            # Set new password
            user.set_password(new_password)
            user.save()

            return JsonResponse({"message": "Password reset successful."}, status=200)

        return JsonResponse({"error": "Invalid request method. Use POST."}, status=405)

    except User.DoesNotExist:
        return JsonResponse({"error": "Invalid UID."}, status=404)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)    


@csrf_exempt
def change_vendor_password(request, vendor_id):
    if request.method == 'POST':
        token = request.COOKIES.get('access_token')

        if not token:
            return JsonResponse({"error": "Authorization token missing"}, status=400)

        try:
            # Decode token to get vendor_id
            access_token = AccessToken(token)
            vendor_id = access_token.get('vendor_id')

            if not vendor_id:
                return JsonResponse({"error": "Invalid token"}, status=400)

            vendor = Services.objects.get(id=vendor_id)

            # Parse JSON data
            data = json.loads(request.body)
            old_password = data.get('old_password')
            new_password = data.get('new_password')

            if not old_password or not new_password:
                return JsonResponse({"error": "Current password and new password required"}, status=400)

            # Verify current password
            if not check_password(old_password, vendor.password):
                return JsonResponse({"error": "Current password is incorrect"}, status=400)

            # Set new password
            vendor.password = make_password(new_password)
            vendor.save()

            return JsonResponse({
                "message": "Password updated successfully",
                "vendor_name": vendor.vendor_name
            })

        except Services.DoesNotExist:
            return JsonResponse({"error": "Vendor not found"}, status=404)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid request method"}, status=405)




# User = get_user_model()

# @api_view(['POST'])
# @authentication_classes([CustomJWTAuthentication])
# @permission_classes([IsAuthenticated])
# def place_order(request):
#     try:
#         data = request.data
#         user = request.user
#         name = data.get('username')
#         contact = data.get('contact')
#         address = data.get('address')
#         coupon_data = data.get('coupon')
#         coupon = json.dumps(coupon_data) if coupon_data else None

#         cart_items = data.get('cartItems', [])
#         total_price = data.get('totalPrice')

#         if not cart_items:
#             return Response({'error': 'Cart is empty'}, status=400)

#         # Prepare product list and update stock
#         items = []
#         for item in cart_items:
#             product_id = item.get('product_id')  # Fixed key
#             quantity = item.get('quantity')

#             try:
#                 product = Product.objects.get(id=product_id)
#             except Product.DoesNotExist:
#                 return Response({'error': f"Product with ID {product_id} not found"}, status=404)

#             if product.stock < quantity:
#                 return Response({'error': f"Insufficient stock for {product.name}"}, status=400)

#             product.stock -= quantity
#             product.save()

#             items.append({
#                 'id': product.id,
#                 'name': product.name,
#                 'price': str(product.price),
#                 'quantity': quantity
#             })

#         # Generate unique order ID
#         order_id = str(uuid.uuid4()).replace('-', '')[:12].upper()

#         # Create Order
#         order = Order.objects.create(
#             user=user,
#             order_id=order_id,
#             name=name,
#             contact=contact,
#             address=address,
#             products=json.dumps(items),
#             total_price=total_price,
#             status='pending',
#             coupon=coupon,
#             created_at=timezone.now()
#         )
#         # Clear the cart
#         CartItem.objects.filter(user=user).delete()

#         return Response({
#             'message': 'Order placed successfully',
#             'order_id': order_id,
#             'order_details': {
#             'name': name,
#             'contact': contact,
#             'address': address,
#             'items': items,
#             'total_price': total_price,
#             'status': 'pending',
#             'created_at': order.created_at,
#             'coupon': json.loads(order.coupon) if order.coupon else None  
#              }
#         }, status=200)

#     except Exception as e:
#         return Response({'error': str(e)}, status=500)


@api_view(['POST'])
@authentication_classes([CustomJWTAuthentication])
@permission_classes([IsAuthenticated])
def place_order(request):
    try:
        data = request.data
        user = request.user
        name = data.get('username')
        contact = data.get('contact')
        address = data.get('address')
        coupon_data = data.get('coupon')
        coupon = json.dumps(coupon_data) if coupon_data else None

        cart_items = data.get('cartItems', [])
        total_price = data.get('totalPrice')

        if not cart_items:
            return Response({'error': 'Cart is empty'}, status=400)

        # Prepare product list and update stock
        items = []
        for item in cart_items:
            product_id = item.get('product_id')
            quantity = item.get('quantity')

            try:
                product = Product.objects.get(id=product_id)
            except Product.DoesNotExist:
                return Response({'error': f"Product with ID {product_id} not found"}, status=404)

            if product.stock < quantity:
                return Response({'error': f"Insufficient stock for {product.name}"}, status=400)

            product.stock -= quantity
            product.save()

            items.append({
                'id': product.id,
                'name': product.name,
                'price': str(product.price),
                'quantity': quantity
            })

        # Generate unique order ID
        order_id = str(uuid.uuid4()).replace('-', '')[:12].upper()

        # Create Order
        order = Order.objects.create(
            user=user,
            order_id=order_id,
            name=name,
            contact=contact,
            address=address,
            products=json.dumps(items),
            total_price=total_price,
            status='pending',
            coupon=coupon,
            created_at=timezone.now()
        )

        # Clear the cart
        CartItem.objects.filter(user=user).delete()

        # Return success response
        return Response({
            'message': 'Order placed successfully',
            'order_id': order_id,
            'order_details': {
                'name': name,
                'contact': contact,
                'address': address,
                'items': items,
                'total_price': total_price,
                'status': 'pending',
                'created_at': order.created_at,
                'coupon': json.loads(order.coupon) if order.coupon else None
            }
        }, status=200)

    except Exception as e:
        return Response({'error': str(e)}, status=500)

# @api_view(['GET'])
# @authentication_classes([CustomJWTAuthentication])
# @permission_classes([IsAuthenticated])
# def my_order (request, order_id):
#     try:
#         order = Order.objects.get(user=request.user, order_id=order_id)
#         return Response({
#             'order_details': {
#                 'name': order.name,
#                 'contact': order.contact,
#                 'address': order.address,
#                 'items': json.loads(order.products),
#                 'total_price': order.total_price,
#                 'status': order.status,
#                 'created_at': order.created_at
#             }
#         }, status=200)
#     except Order.DoesNotExist:
#         return Response({'error': 'Didnt ordered yet. Start ordering'}, status=404)

@api_view(['GET'])
@authentication_classes([CustomJWTAuthentication])
@permission_classes([IsAuthenticated])
def my_orders(request):
    orders = Order.objects.filter(user=request.user).order_by('-created_at')
    
    order_list = []
    for order in orders:
        order_list.append({
            'order_id': order.order_id,
            'status': order.status,
            'total_price': str(order.total_price),
            'coupon': json.loads(order.coupon) if order.coupon else None,
            'items': json.loads(order.products),
            'created_at': order.created_at.strftime("%Y-%m-%d %H:%M:%S")
        })
    
    return Response({'orders': order_list}, status=200)


@api_view(['PATCH'])
@authentication_classes([CustomJWTAuthentication])
@permission_classes([IsAdminUser])
def update_order_status(request, order_id):
    try:
        order = Order.objects.get(order_id=order_id)
        new_status = request.data.get('status')

        valid_statuses = [status[0] for status in Order.STATUS_CHOICES]
        if new_status not in valid_statuses:
            return Response({'error': f"Invalid status. Valid options are: {', '.join(valid_statuses)}"}, status=400)

        send_email = new_status == 'confirmed' and order.status != 'confirmed'
        order.status = new_status
        order.save()

        if send_email:
            try:
                invoice_pdf = generate_invoice_pdf(order)
                first_name = order.user.first_name or order.user.username
                subject = "Your Order is Confirmed - Handcar"
                message = f"Hi {first_name},\n\nYour order has been confirmed. Please find the invoice attached.\n\nThanks,\nHandcar Team"
                from_email = settings.EMAIL_HOST_USER
                to_email = [order.user.email]

                if order.user.email:
                    email = EmailMessage(subject, message, from_email, to_email)
                    email.attach(f"Invoice_{order.order_id}.pdf", invoice_pdf.read(), "application/pdf")
                    email.send()
            except Exception as e:
                print(f"Error sending confirmation email: {e}")

        return Response({'message': f"Order status updated to '{new_status}'"}, status=200)

    except Order.DoesNotExist:
        return Response({'error': 'Order not found'}, status=404)


def promoted_brands_products(request):
    if request.method == 'GET':
        promoted_brands = Brand.objects.filter(promoted=True)
        brands_products = Product.objects.filter(brand__in=promoted_brands)
        product_list = [
            {
                "id": product.id,
                "name": product.name,
                "price": product.price,
                "image": product.image if product.image else None
            }
                for product in brands_products
        ]
        
        return JsonResponse({"promoted_brands_products": product_list}, status=200)
    return JsonResponse({"error": "Invalid HTTP method."}, status=405)




@csrf_exempt
def get_all_orders(request):
    if request.method == 'GET':
        try:
            search_query = request.GET.get('search', '').strip()

            if search_query:
                orders = Order.objects.filter(
                    Q(order_id__icontains=search_query) |
                    Q(name__icontains=search_query) |
                    Q(contact__icontains=search_query)
                ).order_by('-created_at')
            else:
                orders = Order.objects.all().order_by('-created_at')

            order_list = []

            for order in orders:
                try:
                    address = json.loads(order.address) if order.address else None
                except json.JSONDecodeError:
                    address = order.address

                try:
                    items = json.loads(order.products)
                except json.JSONDecodeError:
                    items = []

                try:
                    coupon = json.loads(order.coupon) if order.coupon else None
                except json.JSONDecodeError:
                    coupon = None

                order_list.append({
                    'order_id': order.order_id,
                    'name': order.name,
                    'contact': order.contact,
                    'address': address,
                    'status': order.status,
                    'total_price': str(order.total_price),
                    'items': items,
                    'coupon': coupon,
                    'created_at': order.created_at.strftime("%Y-%m-%d %H:%M:%S")
                })

            return JsonResponse({"orders": order_list}, status=200)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid HTTP method."}, status=405)


@csrf_exempt
def get_nearby_vendor_on_add_subscription(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            address = data.get('address')

            if not address:
                return JsonResponse({'error': 'Address is required for geocoding.'}, status=400)

            subscriber_lat, subscriber_lon = get_geocoded_location(address)
            nearby_vendors = get_nearby_vendors(subscriber_lat, subscriber_lon)

            vendor_data = [
                {
                    'id': vendor.id,
                    'name': vendor.vendor_name,
                    'address': vendor.address,
                    'latitude': vendor.latitude,
                    'longitude': vendor.longitude,
                    'distance_km': vendor.distance,
                }
                for vendor in nearby_vendors
            ]

            return JsonResponse({'nearby_vendors': vendor_data}, status=200)

        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON.'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'Invalid request method. Use POST.'}, status=405)


@csrf_exempt
def get_vendor_subscribers(request, vendor_id):
    if request.method == 'GET':
        try:
            vendor = get_object_or_404(Services, id=vendor_id)

            # Get search query from request
            search_query = request.GET.get('search', '').strip()

            # Filter subscribers assigned to this vendor
            subscribers = Subscriber.objects.filter(assigned_vendor=vendor)

            # Apply email search filter if provided
            if search_query:
                subscribers = subscribers.filter(email__icontains=search_query)

            subscriber_data = [
                {
                    'email': sub.email,
                    'address': sub.address,
                    'service_type': sub.service_type,
                    'plan': sub.plan,
                    'duration': sub.duration,
                    'start_date': sub.start_date.strftime('%Y-%m-%d') if sub.start_date else None,
                    'end_date': sub.end_date.strftime('%Y-%m-%d') if sub.end_date else None,
                }
                for sub in subscribers
            ]

            return JsonResponse({'subscribers': subscriber_data}, status=200)

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid HTTP method'}, status=405)


@csrf_exempt
def get_service_logs_for_vendor(request, vendor_id):
    if request.method != 'GET':
        return JsonResponse({'error': 'Invalid request method'}, status=405)

    try:
        # Fetch the vendor object
        vendor = get_object_or_404(Services, id=vendor_id)

        # Filter logs related to this vendor
        logs = ServiceInteractionLog.objects.filter(service=vendor)

        # Optional search by user's first name
        search_name = request.GET.get('search', '')
        if search_name:
            logs = logs.filter(user__first_name__icontains=search_name)

        # Prepare response
        logs_data = [
            {
                "id": log.id,
                "action": log.get_action_display(),
                "status": log.get_status_display(),
                "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "user_name": log.user.get_full_name() if log.user else "Unknown User",
            }
            for log in logs
        ]

        return JsonResponse({"logs": logs_data}, status=200)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@api_view(["GET"])
@permission_classes([IsAdminUser]) 
def admin_dashboard(request):
    try:
        total_services = Services.objects.count()
        total_accessories = Product.objects.count()
        total_users = User.objects.filter(is_superuser=False, is_staff=False).count()
        total_subscribers = Subscriber.objects.count()
        return JsonResponse({
            "total_services": total_services,
            "total_accessories": total_accessories,
            "total_users": total_users,
            "total_subscribers": total_subscribers
        }, status=200)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500) 



@csrf_exempt
@api_view(["GET"])
def vendor_dashboard(request, vendor_id):
    try:
        # Get vendor instance
        vendor = get_object_or_404(Services, id=vendor_id)

        # Count of subscribers assigned to this vendor
        total_subscribers = Subscriber.objects.filter(assigned_vendor=vendor).count()

        # Count of service interaction logs (service requests)
        total_service_requests = ServiceInteractionLog.objects.filter(service=vendor).count()

        return JsonResponse({
            "total_subscribers": total_subscribers,
            "total_service_requests": total_service_requests,
        }, status=200)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    


@api_view(['GET'])
def service_average_rating(request, service_id):
    try:
        service = get_object_or_404(Services, id=service_id)
        ratings = service.ratings.all()  # related_name = 'ratings' is used here

        if ratings.exists():
            avg_rating = round(sum(r.rating for r in ratings) / ratings.count(), 1)
        else:
            avg_rating = 0

        return JsonResponse({
            'service_id': service.id,
            'vendor_name': service.vendor_name,
            'average_rating': avg_rating,
            'total_reviews': ratings.count()
        }, status=200)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    

@api_view(['GET'])
def product_average_rating(request, product_id):
    try:
        product = get_object_or_404(Product, id=product_id)
        reviews = product.reviews.all()
        if reviews.exists():
            avg_rating = round(sum(review.rating for review in reviews) / reviews.count(), 1)
        else:
            avg_rating = 0
        return JsonResponse({'product_id': product.id, 'average_rating': avg_rating})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def delete_serviceimage(request, image_id):
    if request.method == 'DELETE':
        try:
            image = get_object_or_404(ServiceImage, id=image_id)
            if image.public_id:
                destroy(image.public_id)
            image.delete()
            return JsonResponse({'message': 'Image deleted successfully'}, status=200)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    else:
        return JsonResponse({'error': 'Invalid HTTP method'}, status=405)


from django.core.mail import EmailMessage
from django.http import JsonResponse
from django.conf import settings
from .models import Order
from .utils import generate_invoice_pdf

def confirm_order(request):
    if request.method == "POST":
        user = request.user
        order_id = request.POST.get("order_id")

        try:
            order = Order.objects.get(id=order_id, user=user)
            order.status = "confirmed"
            order.save()

            # Generate the invoice PDF
            invoice_pdf = generate_invoice_pdf(order)

            subject = "Your Order Invoice - Handcar"
            message = f"Hi {user.username},\n\nThanks for your purchase! Please find your invoice attached.\n\nRegards,\nHandcar Team"
            from_email = settings.EMAIL_HOST_USER
            to_email = [user.email]

            email = EmailMessage(subject, message, from_email, to_email)
            email.attach(f"Invoice_{order.id}.pdf", invoice_pdf.read(), "application/pdf")
            email.send()

            return JsonResponse({'status': 'success', 'message': 'Order confirmed and invoice sent!'})

        except Order.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Order not found'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


def home(request):
    return HttpResponse("Hi handcar")


@csrf_exempt
def send_otp_forget_password(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email')

            if not email:
                return JsonResponse({"error": "Email is required."}, status=400)

            User = get_user_model()
            user = User.objects.filter(email=email).first()
            if not user:
                return JsonResponse({"error": "No user found with this email."}, status=404)

            otp = str(random.randint(1000, 9999))
            PasswordResetOTP.objects.create(user=user, otp=otp)

            name = user.first_name or user.username

            send_mail(
                subject="Your OTP for Password Reset",
                message=f"Hi {name},\n\nYour OTP is: {otp}\n\nIt will expire in 10 minutes.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
            )

            return JsonResponse({"message": "OTP sent to email."})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid request method."}, status=405)


@csrf_exempt
def verify_otp_forget_password(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email')
            otp = data.get('otp')

            if not email or not otp:
                return JsonResponse({"error": "Email and OTP are required."}, status=400)

            User = get_user_model()
            user = User.objects.filter(email=email).first()
            if not user:
                return JsonResponse({"error": "User not found."}, status=404)

            otp_obj = PasswordResetOTP.objects.filter(user=user, otp=otp).order_by('-created_at').first()
            if not otp_obj or not otp_obj.is_valid():
                return JsonResponse({"error": "Invalid or expired OTP."}, status=400)

            # Web: mark as verified in session
            request.session[f'otp_verified_{user.id}'] = True

            # Mobile: generate and return token
            otp_token = otp_obj.generate_token()


            return JsonResponse({
                "message": "OTP verified successfully.",
                "otp_token": otp_token
            })
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid request method."}, status=405)


@csrf_exempt
def reset_password_with_otp(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email')
            new_password = data.get('new_password')
            confirm_password = data.get('confirm_password')
            otp_token = data.get('otp_token')  # optional, for mobile

            if not email or not new_password or not confirm_password:
                return JsonResponse({"error": "All fields are required."}, status=400)

            if new_password != confirm_password:
                return JsonResponse({"error": "Passwords do not match."}, status=400)

            User = get_user_model()
            user = User.objects.filter(email=email).first()
            if not user:
                return JsonResponse({"error": "User not found."}, status=404)

            # Web session check
            is_verified = request.session.get(f'otp_verified_{user.id}')

            # Mobile token check
            if not is_verified and otp_token:
                otp_obj = PasswordResetOTP.objects.filter(user=user, token=otp_token).order_by('-created_at').first()
                if otp_obj and otp_obj.is_valid():
                    is_verified = True
                    otp_obj.delete()

            if not is_verified:
                return JsonResponse({"error": "OTP not verified."}, status=403)

            user.set_password(new_password)
            user.save()

            # Cleanup session if used
            request.session.pop(f'otp_verified_{user.id}', None)

            return JsonResponse({"message": "Password reset successful."})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid request method."}, status=405)