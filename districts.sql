-- phpMyAdmin SQL Dump
-- version 3.5.7
-- http://www.phpmyadmin.net
--
-- Host: localhost
-- Generation Time: May 12, 2014 at 02:15 AM
-- Server version: 5.5.29
-- PHP Version: 5.4.10

SET SQL_MODE="NO_AUTO_VALUE_ON_ZERO";
SET time_zone = "+00:00";

--
-- Database: `bd_geocode`
--

-- --------------------------------------------------------

--
-- Table structure for table `districts`
--

CREATE TABLE `districts` (
  `id` int(2) unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(30) NOT NULL,
  `division_id` int(2) unsigned NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB  DEFAULT CHARSET=utf8 AUTO_INCREMENT=65 ;

--
-- Dumping data for table `districts`
--

INSERT INTO `districts` (`id`, `name`, `division_id`) VALUES
(1, 'Dhaka', 3),
(2, 'Faridpur', 3),
(3, 'Gazipur', 3),
(4, 'Gopalganj', 3),
(5, 'Jamalpur', 3),
(6, 'Kishoreganj', 3),
(7, 'Madaripur', 3),
(8, 'Manikganj', 3),
(9, 'Munshiganj', 3),
(10, 'Mymensingh', 3),
(11, 'Narayanganj', 3),
(12, 'Narsingdi', 3),
(13, 'Netrokona', 3),
(14, 'Rajbari', 3),
(15, 'Shariatpur', 3),
(16, 'Sherpur', 3),
(17, 'Tangail', 3),
(18, 'Bogra', 5),
(19, 'Joypurhat', 5),
(20, 'Naogaon', 5),
(21, 'Natore', 5),
(22, 'Nawabganj', 5),
(23, 'Pabna', 5),
(24, 'Rajshahi', 5),
(25, 'Sirajgonj', 5),
(26, 'Dinajpur', 6),
(27, 'Gaibandha', 6),
(28, 'Kurigram', 6),
(29, 'Lalmonirhat', 6),
(30, 'Nilphamari', 6),
(31, 'Panchagarh', 6),
(32, 'Rangpur', 6),
(33, 'Thakurgaon', 6),
(34, 'Barguna', 1),
(35, 'Barisal', 1),
(36, 'Bhola', 1),
(37, 'Jhalokati', 1),
(38, 'Patuakhali', 1),
(39, 'Pirojpur', 1),
(40, 'Bandarban', 2),
(41, 'Brahmanbaria', 2),
(42, 'Chandpur', 2),
(43, 'Chittagong', 2),
(44, 'Comilla', 2),
(45, 'Cox''s Bazar', 2),
(46, 'Feni', 2),
(47, 'Khagrachari', 2),
(48, 'Lakshmipur', 2),
(49, 'Noakhali', 2),
(50, 'Rangamati', 2),
(51, 'Habiganj', 7),
(52, 'Maulvibazar', 7),
(53, 'Sunamganj', 7),
(54, 'Sylhet', 7),
(55, 'Bagerhat', 4),
(56, 'Chuadanga', 4),
(57, 'Jessore', 4),
(58, 'Jhenaidah', 4),
(59, 'Khulna', 4),
(60, 'Kushtia', 4),
(61, 'Magura', 4),
(62, 'Meherpur', 4),
(63, 'Narail', 4),
(64, 'Satkhira', 4);
