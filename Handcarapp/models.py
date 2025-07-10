# models.py
from cloudinary.models import CloudinaryField
from django.core.validators import RegexValidator
from django.db import models
from django.contrib.auth.hashers import make_password

# serializers.py
from datetime import timedelta, date
from email.policy import default
from django.contrib.auth.models import User
from django.utils.timezone import now
from rest_framework import serializers
from django.utils import timezone
import uuid


class Category(models.Model):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name

class Brand(models.Model):
    name = models.CharField(max_length=255)
    promoted =models.BooleanField(default=False)

    def __str__(self):
        return self.name

class Product(models.Model):
    name = models.CharField(max_length=2000)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.URLField(max_length=2000, blank=True, null=True)  # Use URLField for Cloudinary URLs
    description = models.TextField(blank=True)
    stock = models.IntegerField(default=0)
    is_bestseller = models.BooleanField(default=False)
    discount_percentage = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    promoted = models.BooleanField(default=False)


    def average_rating(self):
        reviews = self.reviews.all()
        if reviews:
            return round(sum(review.rating for review in reviews) / reviews.count(), 1)
        return 0



    @property
    def discounted_price(self):
        if self.discount_percentage:
            return self.price - (self.price * self.discount_percentage / 100)
        return self.price


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name']

class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ['id', 'name']

class ProductSerializer(serializers.ModelSerializer):
    category = CategorySerializer()
    brand = BrandSerializer()

    class Meta:
        model = Product
        fields = ['id', 'name', 'price', 'discounted_price', 'rating', 'is_bestseller', 'image', 'category', 'brand']

# Cart Model
class CartItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.user.username} - {self.product.name} (x{self.quantity})"

# Wishlist Model
class WishlistItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.user.username} - {self.product.name}"


# Choices for plan and category
PLAN_CHOICES = [
    ('basic', 'Basic'),
    ('premium', 'Premium'),
    ('luxury', 'Luxury')
]

CATEGORY_CHOICES = [
    ('car_wash', 'Car Wash'),
    ('maintenance', 'Maintenance')
]

DURATION_CHOICES = [
    (6, '6 months'),
    (12, '12 months'),
]

class Subscription(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    plan = models.CharField(max_length=10, choices=PLAN_CHOICES)
    category = models.CharField(max_length=15, choices=CATEGORY_CHOICES)
    duration_months = models.IntegerField(choices=DURATION_CHOICES)  # Restrict duration to 6 or 12 months
    start_date = models.DateField(auto_now_add=True)  # Automatically set when subscription is created
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.user.username} - {self.plan} plan for {self.category}"


class Review(models.Model):
    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.IntegerField()
    comment = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('product', 'user')  # Ensures one review per user per product

    def __str__(self):
        return f"Review by {self.user.username} on {self.product.name} - Rating: {self.rating}"


class Address(models.Model):
    UAE_CITIES = [
        ("Abu Dhabi", "Abu Dhabi"),
        ("Dubai", "Dubai"),
        ("Sharjah", "Sharjah"),
        ("Ajman", "Ajman"),
        ("Fujairah", "Fujairah"),
        ("Ras Al Khaimah", "Ras Al Khaimah"),
        ("Umm Al Quwain", "Umm Al Quwain"),
        ("Al Ain", "Al Ain"),
        ("Khor Fakkan", "Khor Fakkan"),
        ("Dibba Al-Fujairah", "Dibba Al-Fujairah"),
    ]

    HOME = 'Home'
    OFFICE = 'Office'
    ADDRESS_TYPE_CHOICES = [
        (HOME, 'Home'),
        (OFFICE, 'Office'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    name = models.CharField(max_length=255, null=True, blank=True)
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    country = models.CharField(max_length=100, default="United Arab Emirates")
    street = models.CharField(max_length=255)
    building_name = models.CharField(max_length=255)
    floor_apartment_no = models.CharField(max_length=50)
    landmark = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=50, choices=UAE_CITIES)
    area_district = models.CharField(max_length=100)
    address_type = models.CharField(max_length=10, choices=ADDRESS_TYPE_CHOICES, default=HOME)
    is_default = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} - {self.phone_number}"


class Coupon(models.Model):
    name = models.CharField(max_length=100)
    coupon_code = models.CharField(max_length=50, unique=True)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2)
    start_date = models.DateField()
    end_date = models.DateField()
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name

class Plan(models.Model):
    PLAN_DURATION_CHOICES = [
        ('6', '6 Months'),
        ('12', '12 Months'),
    ]

    name = models.CharField(max_length=100)
    service_type = models.CharField(max_length=100)
    duration = models.CharField(max_length=2, choices=PLAN_DURATION_CHOICES)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name






from .utils import geocode_address  # Import the geocode function from utils.py






class ServiceCategory(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name


class Services(models.Model):
    vendor_name = models.CharField(max_length=255,null=True, blank=True)
    phone_number = models.CharField(
        max_length=15,
        unique=True,
        validators=[RegexValidator(regex=r'^\+?1?\d{9,15}$', message="Enter a valid phone number.")],
        null = True, blank = True
    )
    whatsapp_number = models.CharField(
        null = True,
        max_length=15,
        unique=True,
        validators=[RegexValidator(regex=r'^\+?1?\d{9,15}$', message="Enter a valid whatsapp number.")]
    )
    email = models.EmailField(unique=True, null=True, blank=True)
    password = models.CharField(max_length=255, null=True, blank=True)
    address = models.TextField(blank=True, null=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    service_category = models.ForeignKey(ServiceCategory, on_delete=models.CASCADE,null=True)
    service_details = models.TextField(null=True)
    rate = models.IntegerField(null=True)
    image = models.URLField(max_length=2000, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # If address is provided and latitude/longitude is missing, geocode the address
        if self.address and (self.latitude is None or self.longitude is None):
            self.latitude, self.longitude = geocode_address(self.address)

        super().save(*args, **kwargs)

from django.contrib.auth import get_user_model
User = get_user_model()

class Subscriber(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True)
    email = models.EmailField()
    address = models.TextField(blank=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    service_type = models.CharField(max_length=100)
    plan = models.CharField(max_length=100)
    duration = models.IntegerField(help_text="Duration in months")
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True, help_text="Calculated based on duration and start_date")
    assigned_vendors = models.ManyToManyField(Services, blank=True, related_name="subscribers") 

    def save(self, *args, **kwargs):
        if self.start_date and self.duration:
            self.end_date = self.start_date + timedelta(days=self.duration * 30)

        if self.address and (not self.latitude or not self.longitude):
            self.latitude, self.longitude = geocode_address(self.address)

        super().save(*args, **kwargs)


class ServiceImage(models.Model):
    service = models.ForeignKey('Services', on_delete=models.CASCADE, related_name='images')
    image = CloudinaryField('image') # Stores the image in the 'service_images' directory
    public_id = models.CharField(max_length=255, blank=True, null=True) # Stores the Cloudinary public_id helps to delete the image
    uploaded_at = models.DateTimeField(auto_now_add=True)  # Tracks when the image was uploaded

    def __str__(self):
        return f"Image for {self.service.service_name}"


class ServiceInteractionLog(models.Model):
    ACTION_CHOICES = [
        ('CALL', 'Call'),
        ('WHATSAPP', 'WhatsApp Message'),
    ]
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('ACCEPTED', 'Accepted'),
        ('DECLINED', 'Declined'),
    ]

    service = models.ForeignKey('Services', on_delete=models.CASCADE, related_name='interaction_logs')
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    timestamp = models.DateTimeField(default=timezone.now)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    def __str__(self):
        return f"{self.action} - {self.service.vendor_name} at {self.timestamp}"

    class Meta:
        verbose_name = "Service Interaction Log"
        verbose_name_plural = "Service Interaction Logs"
        ordering = ['-timestamp']

class Service_Rating(models.Model):
    service = models.ForeignKey(Services, on_delete=models.CASCADE, related_name='ratings')
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE)  # Optional: To track which user gave the rating
    rating = models.IntegerField()  # Rating value (e.g., 1-5)
    comment = models.TextField(null=True, blank=True)  # Optional: Comment about the service
    created_at = models.DateTimeField(default=now)

    def __str__(self):
        return f"{self.service.vendor_name} - {self.rating} stars"




class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    contact = models.CharField(max_length=20)
    address = models.TextField()
    order_id = models.CharField(max_length=100, unique=True, default=uuid.uuid4)
    products = models.TextField()  # Product summary text
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    coupon = models.TextField(blank=True, null=True, default=None)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.order_id} - {self.user.username}"
    

from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
User = get_user_model()

class PasswordResetOTP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    otp = models.CharField(max_length=6)
    token = models.CharField(max_length=64, null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_valid(self):
        return timezone.now() <= self.created_at + timedelta(minutes=10)

    def generate_token(self):
        self.token = uuid.uuid4().hex
        self.save()
        return self.token