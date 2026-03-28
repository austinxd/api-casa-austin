from rest_framework import serializers

from .models import BlogCategory, BlogPost


class BlogCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = BlogCategory
        fields = ['id', 'name', 'slug', 'description', 'order']


class BlogPostListSerializer(serializers.ModelSerializer):
    category_name = serializers.SerializerMethodField()
    category_slug = serializers.SerializerMethodField()
    featured_image_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = BlogPost
        fields = [
            'id', 'title', 'slug', 'excerpt', 'featured_image_url',
            'thumbnail_url', 'category_name', 'category_slug',
            'author', 'published_date',
        ]

    def get_category_name(self, obj):
        return obj.category.name if obj.category else None

    def get_category_slug(self, obj):
        return obj.category.slug if obj.category else None

    def get_featured_image_url(self, obj):
        if obj.featured_image:
            return obj.featured_image.url
        return None

    def get_thumbnail_url(self, obj):
        if obj.thumbnail:
            return obj.thumbnail.url
        return None


class BlogPostDetailSerializer(serializers.ModelSerializer):
    category = BlogCategorySerializer(read_only=True)
    featured_image_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = BlogPost
        fields = [
            'id', 'title', 'slug', 'content', 'excerpt', 'meta_description',
            'featured_image_url', 'thumbnail_url', 'category',
            'author', 'status', 'published_date', 'created', 'updated',
        ]

    def get_featured_image_url(self, obj):
        if obj.featured_image:
            return obj.featured_image.url
        return None

    def get_thumbnail_url(self, obj):
        if obj.thumbnail:
            return obj.thumbnail.url
        return None


class BlogPostAdminSerializer(serializers.ModelSerializer):
    """Serializer para administración de posts (lectura + edición parcial)."""
    category_name = serializers.SerializerMethodField()
    featured_image_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = BlogPost
        fields = [
            'id', 'title', 'slug', 'content', 'excerpt', 'meta_description',
            'featured_image_url', 'thumbnail_url', 'category', 'category_name',
            'author', 'status', 'published_date', 'created', 'updated',
        ]
        read_only_fields = ['id', 'slug', 'content', 'featured_image_url',
                            'thumbnail_url', 'author', 'published_date',
                            'created', 'updated']

    def _absolute_url(self, relative_url):
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(relative_url)
        return relative_url

    def get_category_name(self, obj):
        return obj.category.name if obj.category else None

    def get_featured_image_url(self, obj):
        if obj.featured_image:
            return self._absolute_url(obj.featured_image.url)
        return None

    def get_thumbnail_url(self, obj):
        if obj.thumbnail:
            return self._absolute_url(obj.thumbnail.url)
        return None
