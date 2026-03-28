from django.contrib import admin
from django.utils.html import format_html

from .models import BlogCategory, BlogPost


@admin.register(BlogCategory)
class BlogCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'order', 'deleted')
    list_filter = ('deleted',)
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['order', 'name']


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'status', 'published_date', 'image_preview', 'deleted')
    list_filter = ('status', 'category', 'deleted')
    search_fields = ('title', 'excerpt')
    prepopulated_fields = {'slug': ('title',)}
    list_editable = ('status',)
    date_hierarchy = 'published_date'
    ordering = ['-published_date']

    fieldsets = (
        ("Contenido", {
            'fields': ('title', 'slug', 'excerpt', 'content', 'featured_image', 'image_preview_large')
        }),
        ("Clasificacion", {
            'fields': ('category', 'author', 'status', 'published_date')
        }),
        ("SEO", {
            'fields': ('meta_description',)
        }),
    )
    readonly_fields = ('image_preview_large',)

    def image_preview(self, obj):
        if obj.thumbnail:
            return format_html('<img src="{}" style="height:40px;border-radius:4px;" />', obj.thumbnail.url)
        if obj.featured_image:
            return format_html('<img src="{}" style="height:40px;border-radius:4px;" />', obj.featured_image.url)
        return "-"
    image_preview.short_description = "Imagen"

    def image_preview_large(self, obj):
        if obj.featured_image:
            return format_html(
                '<img src="{}" style="max-height:300px;border-radius:8px;" />',
                obj.featured_image.url
            )
        return "Sin imagen"
    image_preview_large.short_description = "Vista previa"
