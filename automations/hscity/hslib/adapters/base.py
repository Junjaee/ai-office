from abc import ABC, abstractmethod


class BoardAdapter(ABC):
    @abstractmethod
    def parse_list(self, html: str) -> list[dict]:
        """목록 HTML → [{post_id,title,dept,date,reg_no}, ...]"""

    @abstractmethod
    def list_url(self, board: dict, page: int) -> str:
        """게시판 목록 페이지 URL"""

    @abstractmethod
    def detail_url(self, board: dict, base_url: str, post_id: str) -> str:
        """상세 페이지 URL"""
