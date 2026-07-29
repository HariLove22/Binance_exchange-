--
-- PostgreSQL database dump
--

\restrict IzIlfvRSpXdeTFLGtxM2OfRubdsidIOiRKmmiHcUEOvSlZyhfgEMLqW70xRXmNb

-- Dumped from database version 17.10
-- Dumped by pg_dump version 17.10

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: binance
--

INSERT INTO public.users (id, email, full_name, password_hash, is_active, is_verified, created_at) VALUES (1, 'aarav@example.com', 'Aarav Sharma', '$2b$12$JALiUKyLXDJ9Ag6VeiLu.eAbALb5loIaiwVUa53Jb6JyBe/Da86jO', true, true, '2026-07-21 12:01:01.495587+00');
INSERT INTO public.users (id, email, full_name, password_hash, is_active, is_verified, created_at) VALUES (2, 'priya@novex.dev', 'Priya Verma', '$2b$12$j7MrojuK1N1bI/jiJsds0.CX0P1wuzDnq8GXuphj9wzk5MXz4cNAu', true, true, '2026-07-21 12:09:50.055332+00');
INSERT INTO public.users (id, email, full_name, password_hash, is_active, is_verified, created_at) VALUES (4, 'sahunami843525@gmail.com', 'kamni sahu', '$2b$12$7n35Ii83yXOkKF7C57W0Xu6CVBWIesl8.H2YHxCRkJy1THUgyLC4O', true, true, '2026-07-22 07:08:31.067656+00');
INSERT INTO public.users (id, email, full_name, password_hash, is_active, is_verified, created_at) VALUES (6, 'aravsharma@gmail.com', 'aravsharma', '$2b$12$FWsLlOPI9bBgKSxiiKX5Uut2W.snPoekClBYvM3/ZBK6n3EVi0usi', true, true, '2026-07-22 12:03:08.897405+00');
INSERT INTO public.users (id, email, full_name, password_hash, is_active, is_verified, created_at) VALUES (7, 'aravsharma123@gmail.com', 'aravsharma', '$2b$12$WaRcMAxhwtJMqrOchRlg2u74Xyi/sOh1tVB9WLcQhw80eYZRpSHHq', true, true, '2026-07-22 12:03:26.465266+00');
INSERT INTO public.users (id, email, full_name, password_hash, is_active, is_verified, created_at) VALUES (8, 'honeyt140208@gmail.com', 'richa Trader', '$2b$12$oA.sCL17geMHIqLLG5nmru7a5eFq.q9bQumgdNkD.8BrS1OQJlZVy', true, true, '2026-07-22 12:04:49.860535+00');


--
-- Name: users_id_seq; Type: SEQUENCE SET; Schema: public; Owner: binance
--

SELECT pg_catalog.setval('public.users_id_seq', 8, true);


--
-- PostgreSQL database dump complete
--

\unrestrict IzIlfvRSpXdeTFLGtxM2OfRubdsidIOiRKmmiHcUEOvSlZyhfgEMLqW70xRXmNb

-- fix the id sequence after restoring explicit ids
SELECT setval('users_id_seq', (SELECT MAX(id) FROM users));
