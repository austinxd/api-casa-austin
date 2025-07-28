from rest_framework.pagination import PageNumberPagination

class CustomPagination(PageNumberPagination):

    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 1000
    
    def get_paginated_response(self, data):
        response = super(CustomPagination, self).get_paginated_response(data)

        response.data['actual'] = self.page.number
        response.data['total_paginas'] = self.page.paginator.num_pages
        return response
